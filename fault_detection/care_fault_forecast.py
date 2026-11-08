"""
# CARE wind-turbine fault forecast: BiLSTM + attention over 15-minute windows

Data: "Wind Turbine SCADA Data For Early Fault Detection" (the CARE to Compare collection,
Kaggle `azizkasimov/wind-turbine-scada-data-for-early-fault-detection`): 95 datasets from 36
turbines in 3 wind farms, 10-minute SCADA, 44 of the datasets ending in a labelled fault
event (`event_start` = the turbine needs maintenance).

The question: at an anchor time t ("now"), will this turbine enter a fault event within the
next 7 days, and in which 15-minute window is that most likely? The model outputs a
discrete-time hazard over 672 bins of 15 minutes (7 days),

    h_k = P(onset in bin k | no onset before bin k),

and both answers come from that one output:

    P(fault within 7 days) = 1 - prod_k (1 - h_k)          -> binary alarm, recall
    P(onset in bin k)      = h_k * prod_{j<k} (1 - h_j)    -> most likely window, intervals

An anchor with no onset inside its horizon is right-censored: the survival loss only says
"it survived these bins", it never invents a failure window for a healthy turbine.

`status_type_id` is never an input. In wind farm A a whole week before several labelled
faults is status 4 ("downtime") while the turbine produces normally, and normal datasets
show no such week: there the status follows the fault logbook, so feeding it would hand
the model the label. Inputs are the sensors plus a missing-data flag.

Validation is grouped by turbine (all events of one turbine sit in the same fold), so a
fold never tests on a turbine it trained on.

Subcommands:
    prepare  CSVs -> one 15-minute float16 array per dataset, plus meta.json
    train    cross-validation folds on one device (run two processes for two GPUs)
    report   merges the folds: anchor- and event-level recall, timing error, weekly report
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import queue
import re
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

STEP_MINUTES = 15
STEPS_PER_HOUR = 60 // STEP_MINUTES
HORIZON = 7 * 24 * STEPS_PER_HOUR  # 672 bins = next week
META_COLS = ["time_stamp", "asset_id", "id", "train_test"]
STAT_RE = re.compile(r"^(.*)_(avg|min|max|std)$")


# --------------------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------------------
def find_farms(root: str) -> dict[str, str]:
    """
    Locate the `Wind Farm <X>` folders that hold a `datasets` folder.

    :param root: Folder to search recursively (e.g. `/kaggle/input`).

    :returns farms: Farm letter -> folder path.
    """
    farms: dict[str, str] = {}
    for d in sorted(glob.glob(os.path.join(root, "**", "Wind Farm *"), recursive=True)):
        if os.path.isdir(os.path.join(d, "datasets")):
            farms.setdefault(os.path.basename(d.rstrip("/")).split()[-1], d)
    return farms


def read_table(farm_dir: str, name: str) -> pd.DataFrame:
    """
    Read a farm's `event_info` or `feature_description`, whichever separator it was saved with.

    :param farm_dir: The `Wind Farm <X>` folder.
    :param name: `event_info` or `feature_description`.

    :returns table: The table.
    """
    for fname, sep in ((f"comma_{name}.csv", ","), (f"{name}.csv", ";")):
        path = os.path.join(farm_dir, fname)
        if os.path.exists(path):
            return pd.read_csv(path, sep=sep, encoding="latin-1")
    raise FileNotFoundError(f"no {name} in {farm_dir}")


def dataset_path(farm_dir: str, event_id: int) -> tuple[str, str]:
    """
    Path and separator of one dataset CSV (the comma file, else the semicolon copy).

    The comma file comes first because `read_table` reads `comma_event_info` first: the two
    variants carry different anonymised timestamps, so a CSV and its event table must come
    from the same variant.

    :param farm_dir: The `Wind Farm <X>` folder.
    :param event_id: The dataset's event id.

    :returns path_sep: (path, separator).
    """
    for fname, sep in ((f"comma_{event_id}.csv", ","), (f"{event_id}.csv", ";")):
        path = os.path.join(farm_dir, "datasets", fname)
        if os.path.exists(path):
            return path, sep
    raise FileNotFoundError(f"dataset {event_id} missing in {farm_dir}")


def farm_features(farm_dir: str, event_ids: list[int], stats: tuple[str, ...]) -> dict:
    """
    The sensor columns used for one farm (present in every dataset) and their transforms.

    :param farm_dir: The `Wind Farm <X>` folder.
    :param event_ids: The farm's event ids.
    :param stats: Which 10-minute statistics to keep (`avg`, `min`, `max`, `std`).

    :returns spec: `columns` read from the CSV, `angles` and `counters` among them, `names`
        of the output features in order.
    """
    common: list[str] | None = None
    for eid in event_ids:
        path, sep = dataset_path(farm_dir, eid)
        header = list(pd.read_csv(path, sep=sep, nrows=0).columns)
        cols = [c for c in header if (m := STAT_RE.match(c)) and m.group(2) in stats]
        common = cols if common is None else [c for c in common if c in set(cols)]
    assert common, f"no sensor columns in {farm_dir}"

    angle_sensors: set[str] = set()
    counter_sensors: set[str] = set()
    try:
        desc = read_table(farm_dir, "feature_description")
        truthy = {"true", "1", "yes"}
        for _, row in desc.iterrows():
            name = str(row["sensor_name"]).strip()
            if str(row.get("is_angle", "")).strip().lower() in truthy:
                angle_sensors.add(name)
            if str(row.get("is_counter", "")).strip().lower() in truthy:
                counter_sensors.add(name)
    except FileNotFoundError:
        pass

    angles, counters, names = [], [], []
    for c in common:
        sensor, stat = STAT_RE.match(c).groups()  # type: ignore[union-attr]
        if sensor in angle_sensors and stat != "std":
            angles.append(c)
            names += [f"{c}_sin", f"{c}_cos"]
        elif sensor in counter_sensors:
            counters.append(c)
            names.append(f"{c}_diff")
        else:
            names.append(c)
    names.append("missing")
    return {"columns": common, "angles": angles, "counters": counters, "names": names}


def resample_15min(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Turn 10-minute interval averages into 15-minute interval averages.

    A row stamped t averages (t-10, t]. Each row is split into two 5-minute halves stamped
    t-5 and t, and every 15-minute bin (T-15, T] then averages its three halves, so the
    bin value is the time-weighted mean of what was measured inside it.

    :param frame: 10-minute values indexed by timestamp.

    :returns resampled: 15-minute values on a regular grid; bins without data are NaN.
    """
    half = frame.copy()
    half.index = half.index - pd.Timedelta(minutes=5)
    both = pd.concat([half, frame]).sort_index()
    return both.resample(f"{STEP_MINUTES}min", closed="right", label="right").mean()


def process_dataset(job: dict) -> dict:
    """
    One CSV -> a normalized 15-minute float16 array on disk, plus its metadata.

    Normalization uses the dataset's own `train` part, which precedes the prediction part,
    so no future information enters the scaling.

    :param job: farm, farm_dir, event row, feature spec and output folder.

    :returns meta: The dataset's metadata.
    """
    farm, ev, spec, out = job["farm"], job["event"], job["spec"], job["out"]
    eid = int(ev["event_id"])
    path, sep = dataset_path(job["farm_dir"], eid)
    use = META_COLS + spec["columns"]
    try:
        df = pd.read_csv(path, sep=sep, usecols=use, engine="pyarrow")
    except (ImportError, ValueError):
        df = pd.read_csv(path, sep=sep, usecols=use)
    df["_ts"] = pd.to_datetime(df["time_stamp"])
    df = df.sort_values("_ts").drop_duplicates("_ts").reset_index(drop=True)

    values = {}
    for c in spec["columns"]:
        v = pd.to_numeric(df[c], errors="coerce").to_numpy(np.float64)
        if c in spec["angles"]:
            rad = np.deg2rad(v)
            values[f"{c}_sin"], values[f"{c}_cos"] = np.sin(rad), np.cos(rad)
        elif c in spec["counters"]:
            d = np.diff(v, prepend=np.nan)
            values[f"{c}_diff"] = np.where(d < 0, np.nan, d)
        else:
            values[c] = v
    values["_present"] = np.ones(len(df))
    frame = pd.DataFrame(values, index=pd.DatetimeIndex(df["_ts"]))
    grid = resample_15min(frame)

    sensors = grid[spec["names"][:-1]].to_numpy(np.float64)
    missing = grid["_present"].isna().to_numpy()

    times = grid.index
    train_end_ts = df.loc[df["train_test"] == "train", "_ts"].max()
    train_end_step = int(np.searchsorted(times, train_end_ts, side="right") - 1)
    ref = (np.arange(len(times)) <= train_end_step) & ~missing
    with np.errstate(all="ignore"):
        mean = np.nanmean(sensors[ref], axis=0)
        std = np.nanstd(sensors[ref], axis=0)
    mean = np.nan_to_num(mean, nan=0.0)
    std = np.where(~np.isfinite(std) | (std < 1e-6), 1.0, std)
    z = np.clip((sensors - mean) / std, -10, 10)
    z = np.nan_to_num(z, nan=0.0)
    x = np.concatenate([z, missing[:, None].astype(np.float64)], axis=1)

    def step_of_id(row_id: float) -> int | None:
        if pd.isna(row_id):
            return None
        ts = df.loc[df["id"] >= row_id, "_ts"]
        return None if ts.empty else int(np.searchsorted(times, ts.min(), side="left"))

    label = str(ev["event_label"]).strip()
    onset = step_of_id(ev["event_start_id"]) if label == "anomaly" else None
    key = f"{farm}_{eid}"
    np.save(os.path.join(out, f"X_{key}.npy"), x.astype(np.float16))
    desc = ev.get("event_description")
    return {
        "key": key,
        "farm": farm,
        "event_id": eid,
        "asset": f"{farm}_{df['asset_id'].iloc[0]}",
        "label": label,
        "description": "" if pd.isna(desc) else str(desc),
        "n_steps": int(len(times)),
        "n_features": int(x.shape[1]),
        "grid_start": str(times[0]),
        "train_end_step": train_end_step,
        "report_anchor": train_end_step,
        "onset_step": onset,
        "event_end_step": step_of_id(ev["event_end_id"]),
    }


def cmd_prepare(args: argparse.Namespace) -> None:
    """
    Build the 15-minute arrays for every dataset found under `--input`.

    :param args: Parsed CLI arguments.

    :returns: None.
    """
    from multiprocessing import Pool

    os.makedirs(args.out, exist_ok=True)
    farms = find_farms(args.input)
    if args.farms:
        farms = {k: v for k, v in farms.items() if k in args.farms.split(",")}
    assert farms, f"no 'Wind Farm *' folder with datasets under {args.input}"
    stats = tuple(args.stats.split(","))
    jobs, specs = [], {}
    for farm, farm_dir in farms.items():
        events = read_table(farm_dir, "event_info")
        present = [
            r for _, r in events.iterrows()
            if any(os.path.exists(os.path.join(farm_dir, "datasets", f"{p}{int(r['event_id'])}.csv"))
                   for p in ("", "comma_"))
        ]
        if args.limit:
            present = present[: args.limit]
        if not present:
            continue
        spec = farm_features(farm_dir, [int(r["event_id"]) for r in present], stats)
        specs[farm] = spec
        print(f"farm {farm}: {len(present)} datasets, {len(spec['names'])} features", flush=True)
        jobs += [{"farm": farm, "farm_dir": farm_dir, "event": r.to_dict(), "spec": spec,
                  "out": args.out} for r in present]

    t0, metas = time.time(), []
    with Pool(args.workers) as pool:
        for i, meta in enumerate(pool.imap_unordered(process_dataset, jobs), 1):
            metas.append(meta)
            print(f"[{i}/{len(jobs)}] {meta['key']} {meta['label']:7s} steps={meta['n_steps']} "
                  f"onset={meta['onset_step']} ({time.time() - t0:.0f}s)", flush=True)
    metas.sort(key=lambda m: m["key"])
    with open(os.path.join(args.out, "meta.json"), "w") as f:
        json.dump({"horizon": HORIZON, "step_minutes": STEP_MINUTES,
                   "features": {k: v["names"] for k, v in specs.items()},
                   "datasets": metas}, f, indent=1)
    n_anom = sum(m["label"] == "anomaly" for m in metas)
    print(f"done: {len(metas)} datasets ({n_anom} anomaly) in {time.time() - t0:.0f}s")


# --------------------------------------------------------------------------------------
# data for training
# --------------------------------------------------------------------------------------
class Store:
    """The prepared arrays (memory-mapped, so two training processes share the page cache)."""

    def __init__(self, folder: str):
        with open(os.path.join(folder, "meta.json")) as f:
            self.meta = json.load(f)
        self.ds = self.meta["datasets"]
        self.horizon = int(self.meta["horizon"])
        self.x = [np.load(os.path.join(folder, f"X_{d['key']}.npy"), mmap_mode="r") for d in self.ds]
        self.farms = sorted(self.meta["features"])
        self.farm_of = np.array([self.farms.index(d["farm"]) for d in self.ds])
        self.missing_cum = [np.concatenate([[0.0], np.cumsum(np.asarray(x[:, -1], np.float32))])
                            for x in self.x]


def make_anchors(store: Store, ds_ids, lookback: int, pos_stride: int, neg_stride: int,
                 max_missing: float = 0.5) -> dict[str, np.ndarray]:
    """
    Anchors ("now" points) with their survival targets.

    For anchor t the input is bins t-lookback+1..t and bin k of the horizon is bin t+k.
    `k` is the onset bin (1..horizon) or 0 when no onset falls inside the horizon; `c` is how
    many horizon bins are observed (less than the horizon only near the end of a file).
    Anchors at or after an onset are dropped: the turbine is already in its fault event.

    :param store: The prepared data.
    :param ds_ids: Indices of the datasets to draw from.
    :param lookback: Input length in bins.
    :param pos_stride: Stride for anchors with an onset inside the horizon.
    :param neg_stride: Stride for the others.
    :param max_missing: Drop anchors whose input window is missing more than this share.

    :returns anchors: Arrays `ds`, `t`, `k`, `c`.
    """
    H = store.horizon
    out = {"ds": [], "t": [], "k": [], "c": []}
    for d in ds_ids:
        meta, n = store.ds[d], store.ds[d]["n_steps"]
        t = np.arange(lookback - 1, n - 1)
        onset = meta["onset_step"]
        if onset is not None:
            t = t[t < onset]
            k = onset - t
            k = np.where(k <= H, k, 0)
        else:
            k = np.zeros_like(t)
        c = np.minimum(H, n - 1 - t)
        keep = np.where(k > 0, t % pos_stride == 0, t % neg_stride == 0)
        cum = store.missing_cum[d]
        miss = (cum[t + 1] - cum[t + 1 - lookback]) / lookback
        keep &= miss <= max_missing
        for name, arr in (("ds", np.full_like(t, d)), ("t", t), ("k", k), ("c", c)):
            out[name].append(arr[keep])
    return {k: np.concatenate(v) if v else np.zeros(0, int) for k, v in out.items()}


def farm_batches(farm_of_sample: np.ndarray, idx: np.ndarray, batch: int, rng=None):
    """
    Split sample indices into batches that each hold one farm (farms differ in features).

    :param farm_of_sample: Farm index of every anchor.
    :param idx: The anchor indices to batch.
    :param batch: Batch size.
    :param rng: Shuffles samples and batch order when given.

    :returns batches: List of index arrays.
    """
    out = []
    for f in np.unique(farm_of_sample[idx]):
        sel = idx[farm_of_sample[idx] == f]
        if rng is not None:
            sel = rng.permutation(sel)
        out += [sel[i:i + batch] for i in range(0, len(sel), batch)]
    if rng is not None:
        out = [out[i] for i in rng.permutation(len(out))]
    return out


def gather(store: Store, anchors: dict, sel: np.ndarray, lookback: int) -> np.ndarray:
    """
    Stack the input windows of some anchors.

    :param store: The prepared data.
    :param anchors: The anchor arrays.
    :param sel: Which anchors.
    :param lookback: Input length in bins.

    :returns x: float16 array (batch, lookback, features).
    """
    return np.stack([store.x[d][t - lookback + 1:t + 1]
                     for d, t in zip(anchors["ds"][sel], anchors["t"][sel])])


def prefetch(iterable, depth: int = 6):
    """
    Run a generator in a background thread so batch assembly overlaps the GPU.

    :param iterable: Any iterable.
    :param depth: Queue size.

    :returns generator: The same items.
    """
    q: queue.Queue = queue.Queue(depth)
    end = object()

    def worker():
        for item in iterable:
            q.put(item)
        q.put(end)

    threading.Thread(target=worker, daemon=True).start()
    while (item := q.get()) is not end:
        yield item


# --------------------------------------------------------------------------------------
# model and loss (torch imported lazily: `prepare` and `report` run without it)
# --------------------------------------------------------------------------------------
def build_model(farm_dims: list[int], args: argparse.Namespace, horizon: int):
    """
    BiLSTM with additive attention pooling and a per-farm input projection.

    Each farm has its own Linear layer from its sensors to `d_model` (farms log different
    sensors), then a shared farm embedding, BiLSTM, attention over time and a head emitting
    one hazard logit per 15-minute horizon bin.

    :param farm_dims: Input feature count per farm, in `Store.farms` order.
    :param args: Hyper-parameters.
    :param horizon: Number of output bins.

    :returns model: The torch module.
    """
    import torch
    from torch import nn

    class FaultLSTMAttention(nn.Module):
        def __init__(self):
            super().__init__()
            d, h = args.d_model, args.hidden
            self.enc = nn.ModuleList([
                nn.Sequential(nn.Linear(n, d), nn.LayerNorm(d), nn.GELU(), nn.Dropout(args.dropout))
                for n in farm_dims
            ])
            self.farm_emb = nn.Embedding(len(farm_dims), d)
            self.lstm = nn.LSTM(d, h, num_layers=args.layers, batch_first=True,
                                bidirectional=True, dropout=args.dropout if args.layers > 1 else 0)
            self.att = nn.Sequential(nn.Linear(2 * h, args.att_dim), nn.Tanh(),
                                     nn.Linear(args.att_dim, 1, bias=False))
            self.head = nn.Sequential(nn.Linear(4 * h, 256), nn.GELU(), nn.Dropout(args.dropout),
                                      nn.Linear(256, horizon))
            nn.init.constant_(self.head[-1].bias, args.init_logit)

        def forward(self, x, farm: int):
            z = self.enc[farm](x) + self.farm_emb.weight[farm]
            hs, _ = self.lstm(z)                                   # (B, T, 2h)
            a = torch.softmax(self.att(hs).squeeze(-1).float(), dim=1)  # (B, T)
            ctx = torch.einsum("bt,btd->bd", a.to(hs.dtype), hs)
            last = hs[:, -1]
            return self.head(torch.cat([ctx, last], dim=1)), a

    return FaultLSTMAttention()


def survival_nll(z, k, c, smooth: float = 0.0):
    """
    Discrete-time survival negative log-likelihood over the horizon bins.

    Onset in bin k: log h_k + sum_{j<k} log(1-h_j). Censored after c bins: sum_{j<=c} log(1-h_j).

    :param z: Hazard logits (B, H), float32.
    :param k: Onset bin 1..H, 0 for none (B,).
    :param c: Observed bins for censored anchors (B,).
    :param smooth: Weight of a second-difference penalty on neighbouring logits.

    :returns loss: Mean over the batch.
    """
    import torch
    import torch.nn.functional as F

    log1m, logh = F.logsigmoid(-z), F.logsigmoid(z)
    ar = torch.arange(z.shape[1], device=z.device)[None]
    event = k > 0
    survived = torch.where(event, k - 1, c)
    nll = -(log1m * (ar < survived[:, None])).sum(1)
    nll = nll - torch.where(event, logh.gather(1, (k - 1).clamp_min(0)[:, None]).squeeze(1),
                            torch.zeros_like(nll))
    if smooth > 0:
        nll = nll + smooth * (z[:, 2:] - 2 * z[:, 1:-1] + z[:, :-2]).pow(2).mean(1)
    return nll.mean()


def hazard_summary(z):
    """
    Turn hazard logits into the quantities reported.

    :param z: Hazard logits (B, H), float32, calibration already applied.

    :returns summary: `p_week`, and conditional on an onset inside the week, the `mode`,
        `median`, `q10`, `q90` bins (1-based) and the `pmf`.
    """
    import torch
    import torch.nn.functional as F

    log1m, logh = F.logsigmoid(-z), F.logsigmoid(z)
    cum = torch.cumsum(log1m, 1)
    log_s_prev = torch.cat([torch.zeros_like(cum[:, :1]), cum[:, :-1]], 1)
    pmf = torch.exp(logh + log_s_prev)
    p_week = 1 - torch.exp(cum[:, -1])
    cdf = torch.cumsum(pmf, 1) / pmf.sum(1, keepdim=True).clamp_min(1e-30)
    H = z.shape[1]

    def q(p):
        return ((cdf < p).sum(1) + 1).clamp_max(H)

    return {"p_week": p_week, "mode": pmf.argmax(1) + 1, "median": q(0.5), "q10": q(0.1),
            "q90": q(0.9), "pmf": pmf}


# --------------------------------------------------------------------------------------
# train
# --------------------------------------------------------------------------------------
def fold_split(store: Store, n_folds: int, seed: int):
    """
    Grouped, stratified folds: every turbine's datasets land in one fold.

    :param store: The prepared data.
    :param n_folds: Number of folds.
    :param seed: Shuffle seed (both training processes must use the same).

    :returns folds: List of (train_val indices, test indices).
    """
    from sklearn.model_selection import StratifiedGroupKFold

    y = np.array([d["label"] == "anomaly" for d in store.ds])
    groups = np.array([d["asset"] for d in store.ds])
    sgkf = StratifiedGroupKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    return list(sgkf.split(np.zeros(len(y)), y, groups))


def inner_val(store: Store, ids: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Carve a validation set (by turbine) out of a fold's training datasets.

    :param store: The prepared data.
    :param ids: The fold's train+val dataset indices.
    :param seed: Shuffle seed.

    :returns split: (train ids, val ids).
    """
    from sklearn.model_selection import StratifiedGroupKFold

    y = np.array([store.ds[i]["label"] == "anomaly" for i in ids])
    groups = np.array([store.ds[i]["asset"] for i in ids])
    n = min(5, len(np.unique(groups)))
    if n < 2:
        return ids, ids
    tr, va = next(StratifiedGroupKFold(n_splits=n, shuffle=True, random_state=seed + 1)
                  .split(np.zeros(len(ids)), y, groups))
    return ids[tr], ids[va]


def predict_logits(model, store, anchors, lookback, device, batch=1024, with_att=False):
    """
    Hazard logits for a set of anchors, in anchor order.

    :param model: The model.
    :param store: The prepared data.
    :param anchors: Anchor arrays.
    :param lookback: Input length.
    :param device: Torch device.
    :param batch: Inference batch size.
    :param with_att: Also return attention weights.

    :returns logits: float32 tensor (N, H) on the device (and attention on the CPU).
    """
    import torch

    n = len(anchors["t"])
    farm = store.farm_of[anchors["ds"]]
    out = torch.empty((n, store.horizon), dtype=torch.float32, device=device)
    att = torch.empty((n, lookback), dtype=torch.float32) if with_att else None
    model.eval()
    jobs = farm_batches(farm, np.arange(n), batch)
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.float16,
                                         enabled=device.type == "cuda"):
        for sel, xb in prefetch((s, gather(store, anchors, s, lookback)) for s in jobs):
            x = torch.from_numpy(xb).to(device, non_blocking=True).float()
            z, a = model(x, int(farm[sel[0]]))
            out[torch.from_numpy(sel).to(device)] = z.float()
            if with_att:
                att[torch.from_numpy(sel)] = a.float().cpu()
    return (out, att) if with_att else out


def fit_bias(z, k, c, steps: int = 300) -> float:
    """
    One-parameter calibration: a shift of every hazard logit, fit on validation anchors drawn
    at the natural rate (training over-samples positives, which inflates the hazard).

    :param z: Validation logits (N, H).
    :param k: Onset bins.
    :param c: Observed bins.
    :param steps: Optimizer steps.

    :returns bias: The shift.
    """
    import torch

    z = z.detach()
    b = torch.zeros(1, device=z.device, requires_grad=True)
    opt = torch.optim.Adam([b], lr=0.05)
    with torch.enable_grad():
        for _ in range(steps):
            opt.zero_grad()
            loss = survival_nll(z + b, k, c)
            loss.backward()
            opt.step()
    return float(b.detach())


def pick_threshold(p: np.ndarray, y: np.ndarray, beta: float = 2.0) -> float:
    """
    Threshold maximizing F-beta (beta=2 weighs recall 4x precision: a missed failure costs more).

    :param p: Scores.
    :param y: Binary labels.
    :param beta: F-beta weight.

    :returns threshold: The cut.
    """
    if y.sum() == 0:
        return 0.5
    order = np.argsort(-p)
    ps, ys = p[order], y[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    recall, precision = tp / ys.sum(), tp / (tp + fp)
    f = (1 + beta**2) * precision * recall / np.maximum(beta**2 * precision + recall, 1e-12)
    return float(ps[int(np.argmax(f))])


def run_fold(store: Store, fold: int, train_ids, val_ids, test_ids, args, device) -> None:
    """
    Train one fold, calibrate on its validation turbines, predict its test turbines.

    :param store: The prepared data.
    :param fold: Fold number.
    :param train_ids: Training dataset indices.
    :param val_ids: Validation dataset indices.
    :param test_ids: Test dataset indices.
    :param args: Hyper-parameters.
    :param device: Torch device.

    :returns: None. Writes `fold<k>/` under `--out`.
    """
    import torch
    from sklearn.metrics import roc_auc_score

    out = Path(args.out) / f"fold{fold}"
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed + fold)
    torch.manual_seed(args.seed + fold)
    L = args.lookback

    tr = make_anchors(store, train_ids, L, args.pos_stride, args.neg_stride)
    va = make_anchors(store, val_ids, L, args.neg_stride, args.neg_stride)
    farm_tr = store.farm_of[tr["ds"]]
    pos, neg = np.flatnonzero(tr["k"] > 0), np.flatnonzero(tr["k"] == 0)
    print(f"[fold {fold}] datasets train={len(train_ids)} val={len(val_ids)} test={len(test_ids)} | "
          f"anchors train pos={len(pos)} neg={len(neg)} val={len(va['t'])} "
          f"(val pos={(va['k'] > 0).sum()})", flush=True)
    if len(pos) == 0:
        raise RuntimeError(f"fold {fold}: no positive anchors in training")

    dims = [len(store.meta["features"][f]) for f in store.farms]
    model = build_model(dims, args, store.horizon).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    steps_per_epoch = math.ceil(args.epoch_samples / args.batch) + len(store.farms)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, pct_start=0.1,
                                                total_steps=args.epochs * steps_per_epoch + 10)
    scaler = torch.amp.GradScaler(enabled=device.type == "cuda")
    va_k = torch.from_numpy(va["k"]).to(device)
    va_c = torch.from_numpy(va["c"]).to(device)
    va_y = (va["k"] > 0)
    va_valid = va_y | (va["c"] == store.horizon)

    best, best_epoch, history, bad = float("inf"), -1, [], 0
    for epoch in range(args.epochs):
        t0 = time.time()
        model.train()
        n_pos = int(args.epoch_samples * args.pos_frac)
        idx = np.concatenate([rng.choice(pos, n_pos, replace=len(pos) < n_pos),
                              rng.choice(neg, args.epoch_samples - n_pos,
                                         replace=len(neg) < args.epoch_samples - n_pos)])
        batches = farm_batches(farm_tr, idx, args.batch, rng)
        total, count = 0.0, 0
        for sel, xb in prefetch((s, gather(store, tr, s, L)) for s in batches):
            x = torch.from_numpy(xb).to(device, non_blocking=True).float()
            if args.noise > 0:
                x = x + args.noise * torch.randn_like(x)
            k = torch.from_numpy(tr["k"][sel]).to(device)
            c = torch.from_numpy(tr["c"][sel]).to(device)
            with torch.autocast(device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                z, _ = model(x, int(farm_tr[sel[0]]))
            loss = survival_nll(z.float(), k, c, args.smooth)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            if sched.last_epoch < sched.total_steps - 1:
                sched.step()
            total += float(loss) * len(sel)
            count += len(sel)

        zv = predict_logits(model, store, va, L, device)
        with torch.no_grad():
            b = fit_bias(zv, va_k, va_c, steps=100)
            val_nll = float(survival_nll(zv + b, va_k, va_c))
            pv = hazard_summary(zv + b)["p_week"].cpu().numpy()
        auc = (roc_auc_score(va_y[va_valid], pv[va_valid])
               if 0 < va_y[va_valid].sum() < va_valid.sum() else float("nan"))
        history.append({"epoch": epoch, "train_nll": total / count, "val_nll": val_nll,
                        "val_auc": auc, "seconds": time.time() - t0})
        print(f"[fold {fold}] epoch {epoch:2d} train {total / count:.4f} val {val_nll:.4f} "
              f"val AUC {auc:.3f} ({time.time() - t0:.0f}s)", flush=True)
        if val_nll < best - 1e-4:
            best, best_epoch, bad = val_nll, epoch, 0
            torch.save(model.state_dict(), out / "model.pt")
        else:
            bad += 1
            if bad >= args.patience:
                break

    model.load_state_dict(torch.load(out / "model.pt", map_location=device))
    zv = predict_logits(model, store, va, L, device)
    bias = fit_bias(zv, va_k, va_c)
    pv = hazard_summary(zv + bias)["p_week"].detach().cpu().numpy()
    thr = pick_threshold(pv[va_valid], va_y[va_valid].astype(int))
    # fallback when the validation turbines hold no failure: the training anchors' cut
    if va_y[va_valid].sum() == 0:
        thr = 0.5

    te = make_anchors(store, test_ids, L, args.eval_stride, args.eval_stride)
    zt = predict_logits(model, store, te, L, device)
    with torch.no_grad():
        s = hazard_summary(zt + bias)
    rows = pd.DataFrame({
        "fold": fold,
        "key": [store.ds[d]["key"] for d in te["ds"]],
        "t": te["t"], "k_true": te["k"], "c": te["c"],
        **{n: s[n].cpu().numpy() for n in ("p_week", "mode", "median", "q10", "q90")},
    })
    rows["alarm"] = rows["p_week"] >= thr
    rows.to_csv(out / "test_anchors.csv.gz", index=False)

    # weekly report: one anchor per test turbine, at the end of its training part ("now")
    rep = {"ds": [], "t": [], "k": [], "c": []}
    for d in test_ids:
        m = store.ds[d]
        t = max(m["report_anchor"], L - 1)
        if m["onset_step"] is not None and t >= m["onset_step"]:
            t = m["onset_step"] - 1
        k = 0 if m["onset_step"] is None else m["onset_step"] - t
        for name, v in (("ds", d), ("t", t), ("k", k if 0 < k <= store.horizon else 0),
                        ("c", min(store.horizon, m["n_steps"] - 1 - t))):
            rep[name].append(v)
    rep = {k: np.asarray(v) for k, v in rep.items()}
    zr, att = predict_logits(model, store, rep, L, device, with_att=True)
    with torch.no_grad():
        sr = hazard_summary(zr + bias)
    report = []
    for i, d in enumerate(rep["ds"]):
        m = store.ds[d]
        pmf = sr["pmf"][i].cpu().numpy()
        top = np.argsort(-pmf)[:5] + 1
        lag_h = (L - 1 - np.argsort(-att[i].numpy())[:5]) / STEPS_PER_HOUR
        report.append({
            "key": m["key"], "farm": m["farm"], "asset": m["asset"], "label": m["label"],
            "description": m["description"], "anchor_step": int(rep["t"][i]),
            "grid_start": m["grid_start"], "onset_step": m["onset_step"],
            "p_week": float(sr["p_week"][i]), "alarm": bool(sr["p_week"][i] >= thr),
            "mode": int(sr["mode"][i]), "median": int(sr["median"][i]),
            "q10": int(sr["q10"][i]), "q90": int(sr["q90"][i]),
            "top_bins": top.tolist(), "top_bin_prob": pmf[top - 1].tolist(),
            "pmf_hourly": pmf.reshape(-1, STEPS_PER_HOUR).sum(1).round(6).tolist(),
            "attention_top_lags_hours": lag_h.tolist(),
        })
    with open(out / "summary.json", "w") as f:
        json.dump({"fold": fold, "threshold": thr, "bias": bias, "best_epoch": best_epoch,
                   "best_val_nll": best, "history": history, "args": vars(args),
                   "train": [store.ds[i]["key"] for i in train_ids],
                   "val": [store.ds[i]["key"] for i in val_ids],
                   "test": [store.ds[i]["key"] for i in test_ids], "report": report}, f, indent=1)
    print(f"[fold {fold}] done: best epoch {best_epoch}, threshold {thr:.4f}, bias {bias:+.3f}",
          flush=True)


def cmd_train(args: argparse.Namespace) -> None:
    """
    Train the requested folds sequentially on one device.

    :param args: Parsed CLI arguments.

    :returns: None.
    """
    import torch

    device = torch.device(args.device if torch.cuda.is_available() or args.device == "cpu" else "cpu")
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True
    store = Store(args.data)
    folds = fold_split(store, args.n_folds, args.seed)
    wanted = range(args.n_folds) if args.folds == "all" else [int(f) for f in args.folds.split(",")]
    for fold in wanted:
        trval, test = folds[fold]
        train_ids, val_ids = inner_val(store, trval, args.seed + fold)
        run_fold(store, fold, train_ids, val_ids, test, args, device)


# --------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson 95% interval of a proportion.

    :param k: Successes.
    :param n: Trials.
    :param z: Normal quantile.

    :returns interval: (low, high).
    """
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def bin_window(grid_start: str, anchor: int, k: int) -> str:
    """
    The 15-minute window of horizon bin k, in the dataset's (anonymized) clock.

    :param grid_start: Timestamp of step 0.
    :param anchor: Anchor step.
    :param k: Horizon bin (1-based).

    :returns window: `YYYY-mm-dd HH:MM-HH:MM`.
    """
    end = pd.Timestamp(grid_start) + pd.Timedelta(minutes=STEP_MINUTES * (anchor + k))
    start = end - pd.Timedelta(minutes=STEP_MINUTES)
    return f"{start:%Y-%m-%d %H:%M}-{end:%H:%M}"


def markdown_table(df: pd.DataFrame) -> str:
    """
    A DataFrame as a Markdown table (no `tabulate` dependency).

    :param df: The table.

    :returns markdown: The table text.
    """
    cells = [[str(v) for v in df.columns]] + [[str(v) for v in row] for row in df.itertuples(index=False)]
    lines = ["| " + " | ".join(r) + " |" for r in cells]
    return "\n".join([lines[0], "|" + "---|" * len(df.columns)] + lines[1:])


def cmd_report(args: argparse.Namespace) -> None:
    """
    Merge every fold's held-out predictions into one out-of-fold report.

    :param args: Parsed CLI arguments.

    :returns: None. Writes `metrics.json`, `weekly_report.csv` and `report.md`.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score

    os.makedirs(args.out, exist_ok=True)
    summaries = [json.load(open(p)) for p in sorted(glob.glob(f"{args.runs}/fold*/summary.json"))]
    assert summaries, f"no fold results under {args.runs}"
    anchors = pd.concat([pd.read_csv(p) for p in sorted(glob.glob(f"{args.runs}/fold*/test_anchors.csv.gz"))])
    H = HORIZON
    hours = 1 / STEPS_PER_HOUR
    stride = int(summaries[0]["args"]["eval_stride"])

    # anchor level: "fault within the next 7 days?" on anchors whose week is fully observed
    a = anchors[(anchors.k_true > 0) | (anchors.c == H)].copy()
    a["y"] = a.k_true > 0
    a["farm"] = a.key.str[0]

    def binary(df):
        tp = int((df.alarm & df.y).sum())
        fp = int((df.alarm & ~df.y).sum())
        fn = int((~df.alarm & df.y).sum())
        r = {"anchors": len(df), "positives": int(df.y.sum()), "tp": tp, "fp": fp, "fn": fn,
             "recall": tp / max(tp + fn, 1), "precision": tp / max(tp + fp, 1)}
        r["f1"] = 2 * r["recall"] * r["precision"] / max(r["recall"] + r["precision"], 1e-12)
        if 0 < df.y.sum() < len(df):
            r["roc_auc"] = float(roc_auc_score(df.y, df.p_week))
            r["pr_auc"] = float(average_precision_score(df.y, df.p_week))
        return r

    metrics = {"anchor_level": binary(a),
               "anchor_level_by_farm": {f: binary(g) for f, g in a.groupby("farm")}}

    # event level: was each failure flagged at least once in the week before its onset?
    events, false_alarms = [], []
    meta = {r["key"]: r for s in summaries for r in s["report"]}
    for key, g in anchors.groupby("key"):
        pos = g[g.k_true > 0]
        neg = g[(g.k_true == 0) & (g.c == H)].sort_values("t")
        if len(pos):
            first = pos[pos.alarm]
            events.append({"key": key, "detected": bool(len(first)),
                           "lead_hours": float(first.k_true.max() * hours) if len(first) else None,
                           "max_p_week": float(pos.p_week.max())})
        # false-alarm episodes: alarms on healthy anchors, a gap over 24 h starts a new one
        t_alarm = neg.t[neg.alarm].to_numpy()
        episodes = int(len(t_alarm) > 0) + int((np.diff(t_alarm) > 24 * STEPS_PER_HOUR).sum())
        years = len(neg) * stride * hours / (24 * 365)
        false_alarms.append({"key": key, "episodes": episodes, "healthy_years": years,
                             "label": meta.get(key, {}).get("label")})
    ev = pd.DataFrame(events)
    fa = pd.DataFrame(false_alarms)
    det = int(ev.detected.sum()) if len(ev) else 0
    lo, hi = wilson(det, len(ev))
    normal_fa = fa[fa.label == "normal"]
    metrics["event_level"] = {
        "failures_total": sum(r["label"] == "anomaly" for r in meta.values()),
        "failures": len(ev), "detected": det, "recall": det / max(len(ev), 1),
        "recall_95ci": [lo, hi],
        "median_lead_hours": float(ev.lead_hours.dropna().median()) if det else None,
        "false_alarm_episodes_per_turbine_year":
            float(fa.episodes.sum() / max(fa.healthy_years.sum(), 1e-9)),
        "normal_turbines_with_any_false_alarm":
            f"{int((normal_fa.episodes > 0).sum())}/{len(normal_fa)}",
    }

    # timing: where in the week, on alarmed anchors that truly precede a failure
    p = anchors[(anchors.k_true > 0) & anchors.alarm]
    if len(p):
        err = (p["median"] - p.k_true).abs() * hours
        base = (np.median(anchors.loc[anchors.k_true > 0, "k_true"]) - p.k_true).abs() * hours
        metrics["timing"] = {
            "anchors": len(p),
            "median_abs_error_hours": float(err.median()), "mean_abs_error_hours": float(err.mean()),
            "within_6h": float((err <= 6).mean()), "within_24h": float((err <= 24).mean()),
            "within_15min_window": float((p["mode"] == p.k_true).mean()),
            "interval80_coverage": float(((p.q10 <= p.k_true) & (p.k_true <= p.q90)).mean()),
            "interval80_median_width_hours": float(((p.q90 - p.q10) * hours).median()),
            "naive_constant_median_abs_error_hours": float(base.median()),
        }

    # weekly report at each turbine's "now" (end of its training part), out of fold
    rows = []
    for s in summaries:
        for r in s["report"]:
            onset_k = (r["onset_step"] - r["anchor_step"]) if r["onset_step"] is not None else None
            rows.append({
                "turbine": r["asset"], "dataset": r["key"], "truth": r["label"],
                "p_fault_7d": round(r["p_week"], 4), "needs_maintenance": r["alarm"],
                "most_likely_window": bin_window(r["grid_start"], r["anchor_step"], r["mode"]),
                "median_time": bin_window(r["grid_start"], r["anchor_step"], r["median"]),
                "interval80": f"{bin_window(r['grid_start'], r['anchor_step'], r['q10'])[:16]} .. "
                              f"{bin_window(r['grid_start'], r['anchor_step'], r['q90'])[:16]}",
                "actual_onset": (bin_window(r["grid_start"], r["anchor_step"], onset_k)
                                 if onset_k is not None else ""),
                "onset_in_hours": round(onset_k * hours, 1) if onset_k is not None else None,
                "onset_inside_week": onset_k is not None and 0 < onset_k <= H,
                "hit_interval80": (onset_k is not None and r["q10"] <= onset_k <= r["q90"]),
                "fold": s["fold"], "description": r["description"],
            })
    weekly = pd.DataFrame(rows).sort_values("p_fault_7d", ascending=False)
    weekly.to_csv(f"{args.out}/weekly_report.csv", index=False)
    if len(ev):
        ev.to_csv(f"{args.out}/event_level.csv", index=False)
    metrics["folds"] = [{"fold": s["fold"], "threshold": s["threshold"], "bias": s["bias"],
                         "best_epoch": s["best_epoch"], "best_val_nll": s["best_val_nll"]}
                        for s in summaries]
    with open(f"{args.out}/metrics.json", "w") as f:
        json.dump(metrics, f, indent=1, default=float)

    al, el = metrics["anchor_level"], metrics["event_level"]
    lines = [
        "# CARE fault forecast: BiLSTM + attention, 15-minute windows, 7-day horizon", "",
        f"Out-of-fold over {len(summaries)} folds (grouped by turbine).", "",
        "## Binary: fault within the next 7 days (needs maintenance)", "",
        f"- Anchor level (one anchor every {stride * STEP_MINUTES} min): recall **{al['recall']:.3f}**, precision "
        f"{al['precision']:.3f}, F1 {al['f1']:.3f}, ROC-AUC {al.get('roc_auc', float('nan')):.3f}, "
        f"PR-AUC {al.get('pr_auc', float('nan')):.3f} ({al['positives']} positive of {al['anchors']}).",
        f"- Event level: **{el['detected']}/{el['failures']} failures flagged** in the week before "
        f"onset ({el['failures_total'] - el['failures']} more had no usable anchor in that week), "
        f"recall {el['recall']:.3f} (95% CI {el['recall_95ci'][0]:.2f}-{el['recall_95ci'][1]:.2f}), "
        f"median lead {el['median_lead_hours']} h.",
        f"- False alarms: {el['false_alarm_episodes_per_turbine_year']:.1f} episodes per "
        f"turbine-year of healthy operation; normal turbines with any: "
        f"{el['normal_turbines_with_any_false_alarm']}.", "",
    ]
    if "timing" in metrics:
        tm = metrics["timing"]
        lines += [
            "## When: which 15-minute window", "",
            f"- Median absolute error of the predicted time: **{tm['median_abs_error_hours']:.1f} h** "
            f"(naive constant guess: {tm['naive_constant_median_abs_error_hours']:.1f} h).",
            f"- Within 6 h: {tm['within_6h']:.1%}, within 24 h: {tm['within_24h']:.1%}, "
            f"exact 15-minute window: {tm['within_15min_window']:.2%}.",
            f"- 80% interval: covers the truth {tm['interval80_coverage']:.1%}, median width "
            f"{tm['interval80_median_width_hours']:.0f} h.", "",
        ]
    lines += ["## Weekly report (anchor = end of each turbine's training data)", "",
              markdown_table(weekly.drop(columns=["description", "fold"]))]
    Path(f"{args.out}/report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))


# --------------------------------------------------------------------------------------
def main() -> None:
    """
    Command-line entry point.

    :returns: None.
    """
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prepare")
    pp.add_argument("--input", default="/kaggle/input")
    pp.add_argument("--out", default="/tmp/care15")
    pp.add_argument("--farms", default="", help="comma list, e.g. A,B (default: all found)")
    pp.add_argument("--stats", default="avg", help="10-minute statistics to keep: avg,min,max,std")
    pp.add_argument("--workers", type=int, default=4)
    pp.add_argument("--limit", type=int, default=0, help="datasets per farm, 0 = all")

    pt = sub.add_parser("train")
    pt.add_argument("--data", default="/tmp/care15")
    pt.add_argument("--out", default="/kaggle/working/runs")
    pt.add_argument("--device", default="cuda:0")
    pt.add_argument("--folds", default="all", help="'all' or comma list, e.g. 0,2,4")
    pt.add_argument("--n-folds", type=int, default=5)
    pt.add_argument("--seed", type=int, default=42)
    pt.add_argument("--lookback", type=int, default=192, help="input bins (192 = 48 h)")
    pt.add_argument("--pos-stride", type=int, default=1)
    pt.add_argument("--neg-stride", type=int, default=4)
    pt.add_argument("--eval-stride", type=int, default=4)
    pt.add_argument("--epochs", type=int, default=40)
    pt.add_argument("--patience", type=int, default=6)
    pt.add_argument("--epoch-samples", type=int, default=100_000)
    pt.add_argument("--pos-frac", type=float, default=0.35)
    pt.add_argument("--batch", type=int, default=256)
    pt.add_argument("--lr", type=float, default=1e-3)
    pt.add_argument("--weight-decay", type=float, default=1e-4)
    pt.add_argument("--d-model", type=int, default=128)
    pt.add_argument("--hidden", type=int, default=128)
    pt.add_argument("--layers", type=int, default=2)
    pt.add_argument("--att-dim", type=int, default=64)
    pt.add_argument("--dropout", type=float, default=0.2)
    pt.add_argument("--noise", type=float, default=0.05)
    pt.add_argument("--smooth", type=float, default=0.01)
    pt.add_argument("--init-logit", type=float, default=-7.0)

    pr = sub.add_parser("report")
    pr.add_argument("--runs", default="/kaggle/working/runs")
    pr.add_argument("--out", default="/kaggle/working/report")

    args = p.parse_args()
    {"prepare": cmd_prepare, "train": cmd_train, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
