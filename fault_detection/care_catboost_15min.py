"""
# CARE fault forecast: CatBoost on the LSTM's 15-minute grid

The same anchors and the same censored target as the BiLSTM in `care_fault_forecast.py`, with
window statistics instead of a sequence model, evaluated with the CatBoost baseline's protocol
(`notebooks/care_catboost_baseline.md`).

- Input: `care_fault_forecast.py prepare` output (15-minute time-weighted means of the `_avg`
  columns, sin/cos for angles, differences for counters, a missing flag, z-scored on each
  dataset's own train part). `status_type_id` is never read.
- Anchors: `make_anchors` unchanged for training (lookback 192 bins = 48 h, stride 1 for anchors
  with an onset inside the horizon, stride 4 for the others, anchors at or after an onset
  dropped, windows over 50% missing dropped). Scoring additionally covers every stride-4 anchor
  after an onset, so that every day of the baseline's daily table gets a score.
- Features, per channel over the 48 h window: last value, mean, std, min, max, OLS slope (per
  hour), mean of the last 6 h minus the mean of the 42 h before. The missing flag gives its last
  value and its window mean.
- Target at horizon K days: onset in (t, t + 96 K] bins. Anchors with no onset in the horizon and
  fewer than 96 K observed bins after them are censored and left out.
- Folds: `catboost_baseline/cv_folds.parquet`, scheme `per_farm` (the baseline's and the cached
  LSTM's folds). Inner groups, CatBoost parameters, tree count, threshold rule and isotonic
  calibration as in the baseline.
- Daily score: the maximum over the day's stride-4 anchors (stride 4 only: positives are sampled
  at stride 1, and a maximum over more draws is higher, which would favour positive days).

Subcommands:
    features   prepared arrays -> per-farm anchor table and feature matrix
    cv         cross-validated CatBoost per farm, out-of-fold daily scores, SHAP per fold
    select     SHAP stability + position / season / overlap filters -> shortlist per farm
    report     headline and checks against season only, the daily baseline and the LSTM
    kumo-eval  Kumo Tabular anchor scores (from Kaggle) -> the same run format
    timing     timing error from the k = 1..7 models
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from care_fault_forecast import Store, make_anchors  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "dataset" / "wind_turbine_scada_fault" / "cache"
BASE = CACHE / "catboost_baseline"
LSTM = CACHE / "lstm_attention"
OUT = CACHE / "catboost_15min"
PREPARED = OUT / "prepared"

LOOKBACK = 192          # 48 h of 15-minute bins
SHORT = 24              # last 6 h
POS_STRIDE, NEG_STRIDE, EVAL_STRIDE = 1, 4, 4
BINS_PER_DAY = 96
STATS = ["last", "mean", "std", "min", "max", "slope", "d6h"]
CB_PARAMS = dict(iterations=400, depth=4, learning_rate=0.05, l2_leaf_reg=20, rsm=0.3, border_count=64,
                 loss_function="Logloss", verbose=False, allow_writing_files=False)
FA_BUDGET = 1.0
REARM_DAYS = 7
N_BOOT = 1000


# --------------------------------------------------------------------------------------
# features
# --------------------------------------------------------------------------------------
def window_stats(x: np.ndarray, t: np.ndarray) -> np.ndarray:
    """
    The seven window statistics of every channel at the given anchors.

    :param x: One dataset's prepared array (steps, channels + missing flag), float16.
    :param t: Anchor steps (each >= LOOKBACK - 1).

    :returns features: float32 array (anchors, 7 * channels + 2), channel-major in `STATS` order,
        then the missing flag's last value and window mean.
    """
    from scipy.ndimage import maximum_filter1d, minimum_filter1d

    L, S = LOOKBACK, SHORT
    v = np.asarray(x[:, :-1], np.float64)
    miss = np.asarray(x[:, -1], np.float64)
    n, c = v.shape
    zero = np.zeros((1, c))
    cs = np.vstack([zero, np.cumsum(v, 0)])
    cs2 = np.vstack([zero, np.cumsum(v * v, 0)])
    idx = np.arange(n, dtype=np.float64)[:, None]
    csi = np.vstack([zero, np.cumsum(idx * v, 0)])

    def wsum(cum, end, length):
        return cum[end + 1] - cum[end + 1 - length]

    s1 = wsum(cs, t, L)
    mean = s1 / L
    std = np.sqrt(np.maximum(wsum(cs2, t, L) / L - mean**2, 0.0))
    # trailing window [t-L+1, t] = centred filter output at t - (L//2 - 1) for an even size L
    shift = L // 2 - 1
    mn = minimum_filter1d(v, L, axis=0, mode="nearest")[t - shift]
    mx = maximum_filter1d(v, L, axis=0, mode="nearest")[t - shift]
    j0 = (t - L + 1)[:, None].astype(np.float64)
    sjx = wsum(csi, t, L) - j0 * s1                      # sum over the window of j * x, j = 0..L-1
    jm = (L - 1) / 2
    slope = (sjx - jm * s1) / (L * (L * L - 1) / 12) * 4   # per hour (4 bins)
    last6 = wsum(cs, t, S) / S
    rest = (s1 - wsum(cs, t, S)) / (L - S)
    feats = np.stack([v[t], mean, std, mn, mx, slope, last6 - rest], axis=2)   # (anchors, c, 7)
    cm = np.concatenate([[0.0], np.cumsum(miss)])
    out = np.concatenate([feats.reshape(len(t), -1), miss[t][:, None],
                          ((cm[t + 1] - cm[t + 1 - L]) / L)[:, None]], axis=1)
    return out.astype(np.float32)


def eval_anchors(store: Store, d: int) -> np.ndarray:
    """
    Stride-4 anchors of one dataset at or after its onset (scored, never trained on).

    :param store: The prepared data.
    :param d: Dataset index.

    :returns t: Anchor steps.
    """
    m, n = store.ds[d], store.ds[d]["n_steps"]
    if m["onset_step"] is None:
        return np.zeros(0, int)
    t = np.arange(LOOKBACK - 1, n - 1)
    t = t[(t >= m["onset_step"]) & (t % EVAL_STRIDE == 0)]
    cum = store.missing_cum[d]
    miss = (cum[t + 1] - cum[t + 1 - LOOKBACK]) / LOOKBACK
    return t[miss <= 0.5]


def segment_targets(A: pd.DataFrame, farm: str) -> pd.DataFrame:
    """
    Make the training targets agree across datasets merged into one timeline.

    `make_anchors` sees one dataset at a time. In 5 timelines (A 2, B 1, C 2) another dataset's
    onset lies inside this dataset's train part, on identical rows, so its anchors were labelled
    "no onset" right before and inside that other event. Here every onset of the timeline counts:
    training anchors inside [onset, event end + 14 days] of any event of their timeline are
    dropped from training (kept for scoring), and an onset of another dataset within the horizon
    sets `k` (in 15-minute bins, ceiling), like the dataset's own onset does.

    :param A: Anchor table of one farm.
    :param farm: Farm letter.

    :returns A: The same table with `k`, `train` updated and `seg_fix` marking changed rows.
    """
    meta = pd.read_parquet(LSTM / "meta.parquet")
    ev = meta[(meta["farm"] == farm) & (meta["label"] == "anomaly")]
    A = A.copy()
    A["seg_fix"] = ""
    tau = A["time"].to_numpy()
    seg = A["segment"].to_numpy()
    for _, e in ev.iterrows():
        s, end = np.datetime64(pd.Timestamp(e["event_start"])), np.datetime64(pd.Timestamp(e["event_end"]))
        m = (seg == e["segment"]) & A["train"].to_numpy() & (A["key"].to_numpy() != f"{farm}_{e['event_id']}")
        inside = m & (tau >= s) & (tau <= end + np.timedelta64(14, "D"))
        A.loc[inside, "train"] = False
        A.loc[inside, "seg_fix"] = "dropped"
        ahead = m & ~inside & (tau < s)
        kb = np.ceil((s - tau[ahead]) / np.timedelta64(15, "m")).astype(int)
        k_old = A.loc[ahead, "k"].to_numpy()
        new = (kb <= 7 * BINS_PER_DAY) & ((k_old == 0) | (kb < k_old))
        idx = np.flatnonzero(ahead)[new]
        A.loc[A.index[idx], "k"] = kb[new]
        A.loc[A.index[idx], "seg_fix"] = "relabelled"
    return A


def _features_job(job):
    d, t = job
    store = _features_job.store
    return d, window_stats(store.x[d], t)


def _init_job(folder):
    _features_job.store = Store(folder)


def cmd_features(args: argparse.Namespace) -> None:
    """
    Anchor table and feature matrix per farm.

    :param args: Parsed CLI arguments.

    :returns: None. Writes `anchors_<farm>.parquet` and `X_<farm>.npy` under `--out`.
    """
    Path(args.out).mkdir(parents=True, exist_ok=True)
    store = Store(args.data)
    seg_of = pd.read_parquet(LSTM / "meta.parquet").assign(
        key=lambda m: m["farm"] + "_" + m["event_id"].astype(str)).set_index("key")["segment"]
    for farm in args.farms.split(","):
        t0 = time.time()
        ids = [i for i, m in enumerate(store.ds) if m["farm"] == farm]
        tr = make_anchors(store, ids, LOOKBACK, POS_STRIDE, NEG_STRIDE)
        parts = []
        for d in ids:
            sel = tr["ds"] == d
            a = pd.DataFrame({"ds": d, "t": tr["t"][sel], "k": tr["k"][sel], "c": tr["c"][sel], "train": True})
            te = eval_anchors(store, d)
            b = pd.DataFrame({"ds": d, "t": te, "k": -1, "c": 0, "train": False})   # k = -1: at/after onset
            parts.append(pd.concat([a, b], ignore_index=True))
        A = pd.concat(parts, ignore_index=True)
        A["eval"] = A["t"] % EVAL_STRIDE == 0
        meta = pd.DataFrame(store.ds)
        A["key"] = meta["key"].to_numpy()[A["ds"]]
        A["label"] = meta["label"].to_numpy()[A["ds"]]
        A["segment"] = A["key"].map(seg_of)
        assert A["segment"].notna().all(), "dataset without a timeline in lstm_attention/meta.parquet"
        A["turbine"] = A["segment"].str.split("-").str[0]
        start = pd.to_datetime(meta["grid_start"].to_numpy()[A["ds"]])
        ts = start + pd.to_timedelta(15 * A["t"].to_numpy(), unit="min")    # end of the anchor's bin
        A["time"] = ts
        A["day"] = ((ts - pd.Timedelta(seconds=1)).floor("D") - pd.Timestamp("1970-01-01")).days.astype(np.int64)
        A["doy"] = (ts - pd.Timedelta(seconds=1)).dayofyear.astype(np.int16)
        A["pos_to_train_end"] = (A["t"] - meta["train_end_step"].to_numpy()[A["ds"]]) / BINS_PER_DAY
        A["onset_step"] = meta["onset_step"].to_numpy()[A["ds"]]
        A = segment_targets(A, farm)
        jobs = [(d, g["t"].to_numpy()) for d, g in A.groupby("ds", sort=True)]
        with Pool(args.workers, initializer=_init_job, initargs=(args.data,)) as pool:
            res = dict(pool.imap_unordered(_features_job, jobs))
        A = A.sort_values(["ds", "t"], kind="stable").reset_index(drop=True)
        X = np.concatenate([res[d] for d, _ in jobs])
        names = [f"{c}__{s}" for c in store.meta["features"][farm][:-1] for s in STATS] + ["missing__last", "missing__mean"]
        assert X.shape == (len(A), len(names))
        np.save(Path(args.out) / f"X_{farm}.npy", X)
        A.drop(columns=["ds"]).assign(ds=A["ds"]).to_parquet(Path(args.out) / f"anchors_{farm}.parquet")
        Path(args.out, f"features_{farm}.json").write_text(json.dumps(names))
        print(f"farm {farm}: {len(A):,} anchors ({int(A['train'].sum()):,} train, "
              f"{int((A['train'] & (A['k'] > 0)).sum()):,} with an onset within 7 d; timeline fix: "
              f"{A['seg_fix'].value_counts().drop('', errors='ignore').to_dict()}), {len(names)} features, "
              f"{X.nbytes / 1e9:.2f} GB, {time.time() - t0:.0f}s", flush=True)


# --------------------------------------------------------------------------------------
# baseline protocol (copied from notebooks/care_catboost_baseline.ipynb)
# --------------------------------------------------------------------------------------
def to_day(ts):
    return np.asarray(ts, dtype="datetime64[s]").astype("datetime64[D]").astype(np.int64)


def event_windows(meta):
    rows = []
    for seg, g in meta[meta["label"] == "anomaly"].groupby("segment"):
        w = sorted(zip(to_day(g["event_start"].to_numpy()), to_day(g["event_end"].to_numpy()), g["event_id"]))
        merged = []
        for s, e, eid in w:
            if merged and s <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], e)
                merged[-1][2].append(eid)
            else:
                merged.append([s, e, [eid]])
        for s, e, ids in merged:
            rows.append(dict(segment=seg, s=int(s), e=int(e), event_ids=",".join(map(str, ids))))
    ev = pd.DataFrame(rows)
    ev["turbine"] = ev["segment"].str.split("-").str[0]
    ev["length_days"] = ev["e"] - ev["s"] + 1
    return ev


def inner_groups(train_turbines, seed, n=3):
    t = np.array(sorted(train_turbines))
    np.random.default_rng(1000 + seed).shuffle(t)
    k = min(n, len(t))
    return [t[i::k] for i in range(k)]


def seg_position(F):
    return F.groupby("segment", sort=False).cumcount().to_numpy()


def shifted(a, k, pos):
    out = np.zeros_like(a)
    out[k:] = a[:-k]
    out[pos < k] = False
    return out


def alarm_days(above, pos):
    s = above.astype(int) + shifted(above, 1, pos).astype(int) + shifted(above, 2, pos).astype(int)
    return s >= 2


def notifications(alarm, pos):
    start = alarm & ~shifted(alarm, 1, pos)
    run = np.cumsum(start)
    idx = np.arange(len(alarm))
    first = np.maximum.accumulate(np.where(start, idx, 0))
    return alarm & ((idx - first) % REARM_DAYS == 0) & (run > 0)


def fa_rate(alarm, y, pos):
    neg = y == 0
    months = neg.sum() / 30.0
    return (notifications(alarm, pos) & neg).sum() / months if months > 0 else np.nan


def choose_threshold(score, y, pos):
    ok = np.isfinite(score) & (y == 0)
    if ok.sum() == 0:
        return np.inf
    levels = np.r_[np.linspace(0.5, 0.99, 50), np.linspace(0.9902, 1.0, 50)]
    cand = np.unique(np.quantile(score[ok], levels))
    cand = np.r_[cand, np.nextafter(cand[-1], np.inf)]
    sc = np.where(np.isfinite(score), score, -np.inf)
    rates = np.array([fa_rate(alarm_days(sc >= c, pos), y, pos) for c in cand])
    good = rates <= FA_BUDGET
    tail_ok = np.flip(np.logical_and.accumulate(np.flip(good)))
    return float(cand[np.argmax(tail_ok)]) if tail_ok.any() else np.inf


def ensemble(F, P):
    pos = seg_position(F)
    n = len(F)
    p = P.groupby("row")["p"].mean().reindex(range(n)).to_numpy()
    score = P.groupby("row")["score"].mean().reindex(range(n)).to_numpy()
    al, ab = [], []
    for _, Ps in P.groupby("seed"):
        Ps = Ps.set_index("row").reindex(range(n))
        above = np.nan_to_num(Ps["score"].to_numpy(), nan=-np.inf) >= Ps["thr"].to_numpy()
        ab.append(above)
        al.append(alarm_days(above, pos))
    return dict(p=p, score=score, above=np.mean(ab, 0) >= 0.5, alarm=np.mean(al, 0) >= 0.5)


def per_turbine_parts(F, ev, p, alarm, target, horizon=7):
    from sklearn.metrics import roc_auc_score  # noqa: F401  (imported where summarise needs it)

    y = F[target].to_numpy(float)
    pos = seg_position(F)
    notif = notifications(alarm, pos)
    turb = F["turbine"].to_numpy()
    seg = F["segment"].to_numpy()
    day = F["day"].to_numpy()
    parts = {}
    for t in np.unique(turb):
        m = turb == t
        rows = np.flatnonzero(m & np.isfinite(y) & np.isfinite(p))
        evs = []
        for _, e in ev[ev["turbine"] == t].iterrows():
            w = np.flatnonzero((seg == e["segment"]) & (day >= e["s"] - horizon) & (day <= e["e"]))
            if not (np.isfinite(y[w]) & (y[w] == 1)).any():
                continue
            hit = w[alarm[w]]
            evs.append((len(hit) > 0, e["s"] - day[hit[0]] if len(hit) else np.nan))
        parts[t] = dict(rows=rows, al=alarm[rows], events=evs, fa=int((notif & m & (y == 0)).sum()),
                        neg=int((m & (y == 0)).sum()))
    return parts, y


def summarise(parts, y, p, sample=None):
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    keys = list(parts) if sample is None else sample
    rows = np.concatenate([parts[t]["rows"] for t in keys])
    evs = [e for t in keys for e in parts[t]["events"]]
    yy, pp = y[rows], p[rows]
    al = np.concatenate([parts[t]["al"] for t in keys])
    out = {"prevalence": yy.mean() if len(yy) else np.nan}
    out["day_recall"] = al[yy == 1].mean() if (yy == 1).any() else np.nan
    out["day_specificity"] = 1 - al[yy == 0].mean() if (yy == 0).any() else np.nan
    out["pr_auc"] = average_precision_score(yy, pp) if 0 < yy.sum() < len(yy) else np.nan
    out["roc_auc"] = roc_auc_score(yy, pp) if 0 < yy.sum() < len(yy) else np.nan
    wa = [(roc_auc_score(y[parts[t]["rows"]], p[parts[t]["rows"]]), y[parts[t]["rows"]].sum()) for t in keys
          if 0 < y[parts[t]["rows"]].sum() < len(parts[t]["rows"])]
    out["within_turbine_auc"] = np.average([a for a, _ in wa], weights=[w for _, w in wa]) if wa else np.nan
    out["brier"] = brier_score_loss(yy, pp) if len(yy) else np.nan
    det = np.array([d for d, _ in evs], bool)
    lead = np.array([lead_ for d, lead_ in evs if d], float)
    out["events"] = len(evs)
    out["recall"] = det.mean() if len(det) else np.nan
    out["recall_before_onset"] = np.mean([d and lead_ >= 1 for d, lead_ in evs]) if len(evs) else np.nan
    out["median_lead_days"] = np.median(lead) if len(lead) else np.nan
    neg = sum(parts[t]["neg"] for t in keys)
    out["fa_per_turbine_month"] = sum(parts[t]["fa"] for t in keys) / (neg / 30.0) if neg else np.nan
    return out


def evaluate_E(F, E, target, ev, n_boot=N_BOOT, seed=0):
    """`evaluate` of the baseline, from an ensemble dict (p, score, above, alarm)."""
    parts, y = per_turbine_parts(F, ev, E["p"], E["alarm"], target)
    point = summarise(parts, y, E["p"])
    rng = np.random.default_rng(seed)
    keys = list(parts)
    boots = [summarise(parts, y, E["p"], list(rng.choice(keys, len(keys), replace=True))) for _ in range(n_boot)]
    return dict(point=point, boot=pd.DataFrame(boots), E=E, parts=parts, y=y)


def perm_p(is_anomaly, score, n=5000, seed=0):
    a = np.asarray(is_anomaly, bool)
    r = pd.Series(score).rank().to_numpy()
    n1, n0 = a.sum(), (~a).sum()
    obs = (r[a].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    rng = np.random.default_rng(seed)
    perm = np.array([(r[rng.permutation(a)].sum() - n1 * (n1 + 1) / 2) / (n1 * n0) for _ in range(n)])
    return float((np.sum(perm >= obs) + 1) / (n + 1))


def matched_eval(F, E, meta, farm, before=7, after=14):
    from sklearn.metrics import roc_auc_score

    seg, day = F["segment"].to_numpy(), F["day"].to_numpy()
    y = F["y7"].to_numpy(float)
    rows, d_idx = [], []
    for _, r in meta[meta["farm"] == farm].iterrows():
        s = to_day([r["event_start"]])[0]
        w = np.flatnonzero((seg == r["segment"]) & (day >= s - before) & (day <= s + after) & np.isfinite(E["score"]))
        if len(w) == 0:
            continue
        rows.append(dict(label=r["label"], max_score=np.max(E["score"][w]), alarm=bool(E["alarm"][w].any())))
        d_idx.append(w[np.isfinite(y[w])])
    R = pd.DataFrame(rows)
    d_idx = np.unique(np.concatenate(d_idx))
    yy = y[d_idx]
    return {"dataset AUC (max score)": roc_auc_score(R["label"] == "anomaly", R["max_score"]),
            "permutation p": perm_p(R["label"] == "anomaly", R["max_score"]),
            "day AUC": roc_auc_score(yy, E["score"][d_idx]) if 0 < yy.sum() < len(yy) else np.nan,
            "alarm in anomaly datasets": R.loc[R["label"] == "anomaly", "alarm"].mean(),
            "alarm in normal datasets": R.loc[R["label"] == "normal", "alarm"].mean(),
            "n anomaly / normal": f"{(R['label'] == 'anomaly').sum()} / {(R['label'] == 'normal').sum()}"}


def matched_pre_onset(F, score, meta, farm, before=7):
    from sklearn.metrics import roc_auc_score

    seg, day = F["segment"].to_numpy(), F["day"].to_numpy()
    rows = []
    for _, r in meta[meta["farm"] == farm].iterrows():
        s = to_day([r["event_start"]])[0]
        w = np.flatnonzero((seg == r["segment"]) & (day >= s - before) & (day <= s - 1) & np.isfinite(score))
        if len(w):
            rows.append(dict(label=r["label"], max_score=np.max(score[w]), mean_score=np.mean(score[w])))
    R = pd.DataFrame(rows)
    a = R["label"] == "anomaly"
    return {"dataset AUC (max score, 7 d before)": roc_auc_score(a, R["max_score"]),
            "permutation p": perm_p(a, R["max_score"]),
            "n anomaly / normal": f"{a.sum()} / {(~a).sum()}"}


def daily_table(farm: str) -> pd.DataFrame:
    """
    The baseline's daily rows of one farm, in `oof_daily_risk.parquet` order (= the row index of
    `cv_runs.pkl`), with `y7` and the strict `ys7` (days inside a window left out).

    :param farm: Farm letter.

    :returns F: Daily table.
    """
    o = pd.read_parquet(BASE / "oof_daily_risk.parquet")
    F = o[o["farm"] == farm].reset_index(drop=True).rename(columns={"truth_k7": "y7"})
    F["ys7"] = np.where(F["in_window"], np.nan, F["y7"])
    return F


# --------------------------------------------------------------------------------------
# cv
# --------------------------------------------------------------------------------------
def target(A: pd.DataFrame, horizon_days: int) -> np.ndarray:
    """
    Censored binary target of the training anchors: onset within the horizon, NaN when unknown.

    :param A: Anchor table.
    :param horizon_days: K.

    :returns y: 1, 0 or NaN per anchor (NaN for scoring-only anchors too).
    """
    H = horizon_days * BINS_PER_DAY
    k, c = A["k"].to_numpy(), A["c"].to_numpy()
    y = np.where((k > 0) & (k <= H), 1.0, np.where(c >= H, 0.0, np.nan))
    return np.where(A["train"].to_numpy(), y, np.nan)


def to_daily(A: pd.DataFrame, rows: np.ndarray, prob: np.ndarray, F: pd.DataFrame) -> np.ndarray:
    """
    Daily maximum of the 15-minute scores (stride-4 anchors only), aligned to the daily table.

    :param A: Anchor table.
    :param rows: Anchor indices that were scored.
    :param prob: Their scores.
    :param F: Daily table.

    :returns daily: Score per daily row, NaN where no anchor or the day is not usable.
    """
    keep = A["eval"].to_numpy()[rows]
    d = pd.DataFrame({"segment": A["segment"].to_numpy()[rows][keep], "day": A["day"].to_numpy()[rows][keep],
                      "s": prob[keep]}).groupby(["segment", "day"])["s"].max()
    out = pd.MultiIndex.from_frame(F[["segment", "day"]]).map(d.to_dict().get)
    out = np.array([np.nan if v is None else v for v in out], float)
    out[~F["usable"].to_numpy()] = np.nan
    return out


def cmd_cv(args: argparse.Namespace) -> None:
    """
    Cross-validated CatBoost of one farm at one horizon.

    :param args: Parsed CLI arguments.

    :returns: None. Writes `runs/<name>_<farm>_k<K>.pkl` (daily predictions in the baseline's run
        format, per-fold info with timings, SHAP per fold).
    """
    from catboost import CatBoostClassifier, Pool as CBPool
    from sklearn.isotonic import IsotonicRegression

    farm, K = args.farm, args.horizon
    A = pd.read_parquet(Path(args.out) / f"anchors_{farm}.parquet")
    X = np.load(Path(args.out) / f"X_{farm}.npy", mmap_mode="r")
    names = json.loads(Path(args.out, f"features_{farm}.json").read_text())
    if args.features:
        keep = json.loads(Path(args.features).read_text())[farm]
        cols = np.array([names.index(c) for c in keep])
        names = list(keep)
    else:
        cols = np.arange(len(names))
    F = daily_table(farm)
    yF = F["y7"].to_numpy(float) if K == 7 else horizon_labels(F, K)
    posF = seg_position(F)
    y = target(A, K)
    turbA = A["turbine"].to_numpy()
    turbF = F["turbine"].to_numpy()
    folds = pd.read_parquet(BASE / "cv_folds.parquet")
    wanted = None if args.folds == "all" else [int(f) for f in args.folds.split(",")]
    runs_dir = Path(args.out) / "runs"
    runs_dir.mkdir(exist_ok=True)
    preds, info, shap_rows = [], [], []
    params = dict(CB_PARAMS, thread_count=args.threads)

    def fit_rows(mask):
        r = np.flatnonzero(mask & np.isfinite(y))
        return r, np.ascontiguousarray(X[r][:, cols]), y[r]

    def score_rows(model, mask, ntree=None):
        r = np.flatnonzero(mask)
        p = np.empty(len(r))
        for i in range(0, len(r), 200_000):
            rr = r[i:i + 200_000]
            p[i:i + 200_000] = model.predict_proba(np.ascontiguousarray(X[rr][:, cols]),
                                                   ntree_end=ntree or 0)[:, 1]
        return r, p

    for seed in [int(s) for s in args.seeds.split(",")]:
        fo = folds[(folds["scheme"] == "per_farm") & (folds["farm"] == farm) & (folds["seed"] == seed)]
        fo = fo.set_index("turbine")["fold"]
        foldA, foldF = pd.Series(turbA).map(fo).to_numpy(), pd.Series(turbF).map(fo).to_numpy()
        score, pcal, thr_row = (np.full(len(F), np.nan) for _ in range(3))
        for k in np.unique(foldF):
            if wanted is not None and k not in wanted:
                continue
            t0 = time.time()
            trA, teA, trF, teF = foldA != k, foldA == k, foldF != k, foldF == k
            oof = np.full(len(F), np.nan)
            fits, t_inner = [], []
            for g in inner_groups(np.unique(turbA[trA]), seed):
                va = trA & np.isin(turbA, g)
                r_fit, X_fit, y_fit = fit_rows(trA & ~va)
                r_ev, X_ev, y_ev = fit_rows(va)
                if y_fit.sum() == 0 or len(r_ev) == 0:
                    continue
                ti = time.time()
                m = CatBoostClassifier(**params, random_seed=seed)
                m.fit(X_fit, y_fit, eval_set=(X_ev, y_ev), early_stopping_rounds=50, use_best_model=False)
                t_inner.append(time.time() - ti)
                fits.append((m, va, m.get_best_iteration() + 1))
                del X_fit, X_ev
            n_star = int(np.clip(np.median([b for *_, b in fits]), 30, CB_PARAMS["iterations"]))
            for m, va, _ in fits:
                r, p = score_rows(m, va & A["eval"].to_numpy(), min(n_star, m.tree_count_))
                d = to_daily(A, r, p, F)
                vaF = np.isin(turbF, np.unique(turbA[va]))
                oof[vaF] = d[vaF]
            r_fit, X_fit, y_fit = fit_rows(trA)
            ti = time.time()
            final = CatBoostClassifier(**dict(params, iterations=n_star), random_seed=seed)
            final.fit(X_fit, y_fit)
            t_final = time.time() - ti
            del X_fit
            r, p = score_rows(final, teA & A["eval"].to_numpy())
            d = to_daily(A, r, p, F)
            score[teF] = d[teF]
            if args.save_anchor_scores:
                pd.DataFrame({"row": r, "p": p.astype(np.float32)}).to_parquet(
                    runs_dir / f"{args.name}_{farm}_k{K}_s{seed}_f{k}_anchors.parquet")
            if seed == int(args.seeds.split(",")[0]) and not args.no_shap:
                ev = np.flatnonzero(teA & A["eval"].to_numpy())
                rng = np.random.default_rng(seed)
                if len(ev) > args.shap_rows:
                    ev = np.sort(rng.choice(ev, args.shap_rows, replace=False))
                sv = final.get_feature_importance(CBPool(np.ascontiguousarray(X[ev][:, cols])), type="ShapValues")[:, :-1]
                shap_rows.append(pd.DataFrame({"feature": names, "fold": k, "n": len(ev),
                                               "mean_abs_shap": np.abs(sv).mean(0)}))
            thr = choose_threshold(oof[trF], yF[trF], posF[trF])
            cal = trF & np.isfinite(yF) & np.isfinite(oof)
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof[cal], yF[cal])
            sel = teF & np.isfinite(score)
            pcal[sel] = iso.predict(score[sel])
            thr_row[teF] = thr
            info.append(dict(seed=seed, fold=int(k), n_trees=n_star, threshold=thr, n_fit=len(r_fit),
                             n_pos=int(y_fit.sum()), n_features=len(cols),
                             seconds_inner=float(np.sum(t_inner)), seconds_final=t_final,
                             seconds_total=time.time() - t0))
            print(f"[{farm} k={K} seed {seed} fold {k}] fit rows {len(r_fit):,} (pos {int(y_fit.sum()):,}), "
                  f"{len(cols)} features, trees {n_star}, inner {np.sum(t_inner):.0f}s, final {t_final:.0f}s, "
                  f"total {time.time() - t0:.0f}s", flush=True)
        preds.append(pd.DataFrame({"seed": seed, "row": np.arange(len(F)), "fold": foldF, "score": score,
                                   "p": pcal, "thr": thr_row}))
    out = dict(pred=pd.concat(preds, ignore_index=True), info=pd.DataFrame(info),
               shap=pd.concat(shap_rows, ignore_index=True) if shap_rows else None, features=names)
    suffix = "" if wanted is None else "_folds" + "-".join(map(str, wanted))
    pd.to_pickle(out, runs_dir / f"{args.name}_{farm}_k{K}{suffix}.pkl")


def horizon_labels(F: pd.DataFrame, k: int) -> np.ndarray:
    """
    The baseline's main target at horizon k, rebuilt from `y7`, `in_window`, `days_to_onset`.

    :param F: Daily table.
    :param k: Horizon in days.

    :returns y: 1, 0 or NaN per day.
    """
    dist, inw = F["days_to_onset"].to_numpy(), F["in_window"].to_numpy()
    usable = F["usable"].to_numpy()
    gray7 = ~inw & (dist > 7) & (dist <= 14)
    repair = usable & np.isnan(F["y7"].to_numpy()) & ~gray7 & ~inw
    pos = inw | (dist <= k)
    gray = ~pos & (dist > k) & (dist <= k + 7)
    return np.where(~usable | repair | gray, np.nan, pos.astype(float))


# --------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------
LSTM_TABLES = {"LSTM-attention (all channels)": "lstm_all",
               "LSTM q672 centred": "q672_centred",
               "LSTM q672 residual": "q672_residual"}


def model_ensembles(farm: str, F: pd.DataFrame, extra: dict[str, str]) -> dict[str, dict]:
    """
    Ensemble dicts (p, score, above, alarm) of every model to compare, on the baseline's rows.

    :param farm: Farm letter.
    :param F: Daily table.
    :param extra: Label -> run name under `runs/` (`<name>_<farm>_k7.pkl`) for the new models.

    :returns E: Label -> ensemble dict.
    """
    runs = pd.read_pickle(BASE / "cv_runs.pkl")
    out = {"season only": ensemble(F, runs[f"{farm}|season|y7"]["pred"]),
           "CatBoost daily (baseline)": ensemble(F, runs[f"{farm}|full|y7"]["pred"])}
    for label, name in LSTM_TABLES.items():
        o = pd.read_parquet(LSTM / f"oof_daily_risk_{name}.parquet")
        o = o[o["farm"] == farm].reset_index(drop=True)
        assert (o[["segment", "day"]].to_numpy() == F[["segment", "day"]].to_numpy()).all()
        out[label] = dict(p=o["risk_k7"].to_numpy() / 100, score=o["score_k7"].to_numpy(),
                          above=o["above_threshold"].to_numpy(), alarm=o["alarm"].to_numpy())
    for label, name in extra.items():
        path = OUT / "runs" / f"{name}_{farm}_k7.pkl"
        if path.exists():
            out[label] = ensemble(F, pd.read_pickle(path)["pred"])
    return out


def ci(res, col, fmt="{:.3f}"):
    v, b = res["point"][col], res["boot"][col]
    lo, hi = np.nanpercentile(b, [2.5, 97.5])
    return f"{fmt.format(v)} [{fmt.format(lo)}, {fmt.format(hi)}]"


def paired(ra, rb, col="roc_auc"):
    d = (ra["boot"][col] - rb["boot"][col]).to_numpy()
    lo, hi = np.nanpercentile(d, [2.5, 97.5])
    diff = ra["point"][col] - rb["point"][col]
    return f"{diff:+.3f} [{lo:+.3f}, {hi:+.3f}]", ("yes" if lo > 0 else ("no, worse" if hi < 0 else "not shown"))


def cmd_report(args: argparse.Namespace) -> None:
    """
    Headline and checks of every model, main target (y7) and strict pre-onset target (ys7).

    :param args: Parsed CLI arguments.

    :returns: None. Writes `results_headline.csv`, `results_checks.csv` under `--out`.
    """
    extra = dict(x.split("=", 1) for x in args.models.split(",")) if args.models else {}
    meta = pd.read_parquet(LSTM / "meta.parquet")
    head, checks = [], []
    for farm in args.farms.split(","):
        F = daily_table(farm)
        ev = event_windows(meta[meta["farm"] == farm])
        Es = model_ensembles(farm, F, extra)
        for tgt, tname in (("y7", "main: inside or entering within 7 d"), ("ys7", "strict: onset within 7 d")):
            R = {label: evaluate_E(F, E, tgt, ev, n_boot=args.n_boot) for label, E in Es.items()}
            for label, r in R.items():
                pt = r["point"]
                head.append({"target": tname, "farm": farm, "model": label,
                             "ROC-AUC pooled [95% CI]": ci(r, "roc_auc"),
                             "ROC-AUC within turbine [95% CI]": ci(r, "within_turbine_auc"),
                             "event recall [95% CI]": ci(r, "recall", "{:.2f}"),
                             "false alarms / turbine-month": round(pt["fa_per_turbine_month"], 2),
                             "PR-AUC": round(pt["pr_auc"], 3), "prevalence": round(pt["prevalence"], 3),
                             "days scored": int(sum(len(v["rows"]) for v in r["parts"].values())),
                             "events": pt["events"]})
                if label == "season only":
                    continue
                d_s, v_s = paired(r, R["season only"])
                d_b, v_b = paired(r, R["CatBoost daily (baseline)"])
                d_bw, v_bw = paired(r, R["CatBoost daily (baseline)"], "within_turbine_auc")
                row = {"target": tname, "farm": farm, "model": label, "ROC-AUC": round(pt["roc_auc"], 3),
                       "vs season only [95% CI]": d_s, "beats season?": v_s,
                       "vs CatBoost daily [95% CI]": d_b, "beats baseline?": v_b,
                       "vs CatBoost daily, within turbine [95% CI]": d_bw, "beats baseline within?": v_bw}
                if tgt == "y7":
                    mt = matched_eval(F, Es[label], meta, farm)
                    pre = matched_pre_onset(F, Es[label]["score"], meta, farm)
                    row.update({"same-position dataset AUC": round(mt["dataset AUC (max score)"], 3),
                                "same-position p": round(mt["permutation p"], 3),
                                "alarm anomaly / normal": f"{mt['alarm in anomaly datasets']:.2f} / "
                                                          f"{mt['alarm in normal datasets']:.2f}",
                                "pre-onset dataset AUC": round(pre["dataset AUC (max score, 7 d before)"], 3),
                                "pre-onset p": round(pre["permutation p"], 3)})
                checks.append(row)
            print(f"farm {farm} {tgt} done", flush=True)
    pd.DataFrame(head).to_csv(Path(args.out) / f"results_headline{args.suffix}.csv", index=False)
    pd.DataFrame(checks).to_csv(Path(args.out) / f"results_checks{args.suffix}.csv", index=False)


# --------------------------------------------------------------------------------------
# select
# --------------------------------------------------------------------------------------
def auc_fast(score: np.ndarray, y: np.ndarray) -> float:
    """ROC-AUC by ranks (ties averaged), NaN when one class is empty."""
    ok = np.isfinite(score)
    s, yy = score[ok], y[ok].astype(bool)
    n1, n0 = yy.sum(), (~yy).sum()
    if n1 == 0 or n0 == 0:
        return np.nan
    r = pd.Series(s).rank().to_numpy()
    return float((r[yy].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def overlap_coef(a: np.ndarray, b: np.ndarray, bins: int = 40) -> float:
    """Overlap coefficient of two distributions (1 = identical) on common quantile bins."""
    edges = np.unique(np.quantile(np.r_[a, b], np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 1.0
    ha = np.histogram(a, edges)[0] / max(len(a), 1)
    hb = np.histogram(b, edges)[0] / max(len(b), 1)
    return float(np.minimum(ha, hb).sum())


def feature_screen(farm: str) -> pd.DataFrame:
    """
    Per feature: label AUC, season-adjusted label AUC, position AUC, class overlap.

    Rows: stride-4 training anchors (positives thinned to stride 4 too, so both classes are
    sampled alike).
    - label AUC: onset within 7 d against not;
    - season-adjusted: the same after removing a 2-harmonic day-of-year curve fitted on the
      negatives (Farm A's ranking was season in the feature explorer);
    - position AUC: normal datasets only, the 14 days around the end of the train part
      (where positives sit in anomaly datasets) against days 300 to 60 before it. A feature that
      separates these in healthy turbines reads the dataset geometry, not the fault;
    - overlap: overlap coefficient of the "fails" and "does not fail" distributions.

    :param farm: Farm letter.

    :returns table: One row per feature.
    """
    A = pd.read_parquet(OUT / f"anchors_{farm}.parquet")
    X = np.load(OUT / f"X_{farm}.npy", mmap_mode="r")
    names = json.loads((OUT / f"features_{farm}.json").read_text())
    y = target(A, 7)
    rows = np.flatnonzero(A["train"].to_numpy() & A["eval"].to_numpy() & np.isfinite(y))
    yy = y[rows]
    doy = A["doy"].to_numpy()[rows] * 2 * np.pi / 365.25
    S = np.column_stack([np.ones(len(rows)), np.sin(doy), np.cos(doy), np.sin(2 * doy), np.cos(2 * doy)])
    normal = (A["label"].to_numpy() == "normal")
    pt = A["pos_to_train_end"].to_numpy()
    pos_rows = np.flatnonzero(normal & A["eval"].to_numpy() & (((pt >= -7) & (pt <= 7)) | ((pt >= -300) & (pt <= -60))))
    pos_y = (pt[pos_rows] >= -7).astype(float)
    neg = yy == 0
    out = []
    for j in range(0, len(names), 64):
        block = np.asarray(X[rows, j:j + 64], np.float64)
        pblock = np.asarray(X[pos_rows, j:j + 64], np.float64)
        beta, *_ = np.linalg.lstsq(S[neg], block[neg], rcond=None)
        resid = block - S @ beta
        for i in range(block.shape[1]):
            v = block[:, i]
            out.append({"feature": names[j + i], "label_auc": auc_fast(v, yy),
                        "season_adj_auc": auc_fast(resid[:, i], yy),
                        "position_auc": auc_fast(pblock[:, i], pos_y),
                        "overlap": overlap_coef(v[yy == 1], v[yy == 0]),
                        "season_r2": 1 - np.var(resid[neg, i]) / max(np.var(v[neg]), 1e-12)})
    return pd.DataFrame(out)


def cmd_select(args: argparse.Namespace) -> None:
    """
    Shortlist per farm: SHAP-stable features that pass the position, season, status and
    overlap filters.

    Stable: in the top `--top` by mean |SHAP| (test turbines, final model of the fold) in at least
    80% of the folds (4 of 5 in A and C, 8 of 9 in B).
    Filters: `status_type_id` never enters (asserted); position: |position AUC - 0.5| >= 0.15;
    season: the label signal is mostly season (|adjusted AUC - 0.5| < half of |AUC - 0.5|, with
    |AUC - 0.5| >= 0.05); overlap: overlap coefficient >= 0.98.

    :param args: Parsed CLI arguments.

    :returns: None. Writes `screen_<farm>.csv` and `shortlist.json` under `--out`.
    """
    short = {}
    for farm in args.farms.split(","):
        run = pd.read_pickle(OUT / "runs" / f"{args.run}_{farm}_k7.pkl")
        sh = run["shap"]
        assert not any("status" in f for f in run["features"]), "status_type_id must never be an input"
        n_folds = sh["fold"].nunique()
        need = int(np.ceil(0.8 * n_folds))
        sh = sh.assign(rank=sh.groupby("fold")["mean_abs_shap"].rank(ascending=False, method="first"))
        st = sh.groupby("feature").agg(mean_abs_shap=("mean_abs_shap", "mean"),
                                       folds_in_top=("rank", lambda r: int((r <= args.top).sum())))
        scr = feature_screen(farm).set_index("feature").join(st)
        a = (scr["label_auc"] - 0.5).abs()
        scr["stable"] = scr["folds_in_top"] >= need
        scr["flag_position"] = (scr["position_auc"] - 0.5).abs() >= 0.15
        scr["flag_season"] = (a >= 0.05) & ((scr["season_adj_auc"] - 0.5).abs() < 0.5 * a)
        scr["flag_overlap"] = scr["overlap"] >= 0.98
        scr["kept"] = scr["stable"] & ~scr["flag_position"] & ~scr["flag_season"] & ~scr["flag_overlap"]
        scr = scr.sort_values("mean_abs_shap", ascending=False)
        kept = scr.index[scr["kept"]].tolist()[: args.max_features]
        scr["shortlist"] = scr.index.isin(kept)
        scr.to_csv(Path(args.out) / f"screen_{farm}.csv")
        short[farm] = kept
        print(f"farm {farm}: {n_folds} folds (stable = top {args.top} in >= {need}), stable {int(scr['stable'].sum())}, "
              f"flagged among stable: position {int((scr['stable'] & scr['flag_position']).sum())}, "
              f"season {int((scr['stable'] & scr['flag_season']).sum())}, "
              f"overlap {int((scr['stable'] & scr['flag_overlap']).sum())} -> shortlist {len(kept)}", flush=True)
    Path(args.out, "shortlist.json").write_text(json.dumps(short, indent=1))


# --------------------------------------------------------------------------------------
# kumo-eval
# --------------------------------------------------------------------------------------
def cmd_kumo_eval(args: argparse.Namespace) -> None:
    """
    Kumo Tabular anchor scores (from Kaggle) -> the baseline run format, like `cv` does for
    CatBoost: daily maximum, threshold and isotonic calibration from the inner fits.

    :param args: Parsed CLI arguments.

    :returns: None. Writes `runs/<name>_<farm>_k7.pkl`.
    """
    from sklearn.isotonic import IsotonicRegression

    folds = pd.read_parquet(BASE / "cv_folds.parquet")
    for farm in args.farms.split(","):
        path = Path(args.kumo) / f"kumo_{farm}_scores.parquet"
        if not path.exists():
            print(f"farm {farm}: no Kumo scores", flush=True)
            continue
        S = pd.read_parquet(path)
        A = pd.read_parquet(OUT / f"anchors_{farm}.parquet", columns=["eval", "segment", "day", "turbine"])
        F = daily_table(farm)
        yF, posF, turbF = F["y7"].to_numpy(float), seg_position(F), F["turbine"].to_numpy()
        fo = folds[(folds["scheme"] == "per_farm") & (folds["farm"] == farm) & (folds["seed"] == args.seed)]
        foldF = pd.Series(turbF).map(fo.set_index("turbine")["fold"]).to_numpy()
        score, pcal, thr_row = (np.full(len(F), np.nan) for _ in range(3))
        for k, g in S.groupby("fold"):
            trF, teF = foldF != k, foldF == k
            oof = np.full(len(F), np.nan)
            for _, gi in g[g["stage"] == "inner"].groupby("group"):
                d = to_daily(A, gi["row"].to_numpy(), gi["p"].to_numpy(float), F)
                vaF = np.isin(turbF, A["turbine"].to_numpy()[gi["row"].to_numpy()]) & trF
                oof[vaF] = d[vaF]
            fin = g[g["stage"] == "final"]
            d = to_daily(A, fin["row"].to_numpy(), fin["p"].to_numpy(float), F)
            score[teF] = d[teF]
            thr = choose_threshold(oof[trF], yF[trF], posF[trF])
            cal = trF & np.isfinite(yF) & np.isfinite(oof)
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof[cal], yF[cal])
            sel = teF & np.isfinite(score)
            pcal[sel] = iso.predict(score[sel])
            thr_row[teF] = thr
        pred = pd.DataFrame({"seed": args.seed, "row": np.arange(len(F)), "fold": foldF, "score": score,
                             "p": pcal, "thr": thr_row})
        pd.to_pickle(dict(pred=pred, info=None, shap=None, features=None),
                     OUT / "runs" / f"{args.name}_{farm}_k7.pkl")
        print(f"farm {farm}: {S['fold'].nunique()} folds, {int(np.isfinite(score).sum())} scored days", flush=True)


# --------------------------------------------------------------------------------------
# timing
# --------------------------------------------------------------------------------------
def cmd_timing(args: argparse.Namespace) -> None:
    """
    Timing error from the seven horizon models (k = 1..7 days, seed 0, out of fold), the LSTM's
    protocol: test anchors 1 to 7 days before an onset that has a logged time (not 00:00), the
    cumulative risks R_k made monotone, the conditional distribution over the week spread
    uniformly inside each day, its median and 10-90% interval against the true onset bin; the
    reference is a uniform curve (median bin 336.5).

    :param args: Parsed CLI arguments.

    :returns: None. Writes `results_timing.csv`.
    """
    meta = pd.read_parquet(LSTM / "meta.parquet").assign(key=lambda m: m["farm"] + "_" + m["event_id"].astype(str))
    logged = set(meta.loc[(meta["label"] == "anomaly")
                          & (pd.to_datetime(meta["event_start"]).dt.strftime("%H:%M") != "00:00"), "key"])
    rows = []
    for farm in args.farms.split(","):
        A = pd.read_parquet(OUT / f"anchors_{farm}.parquet", columns=["key", "k", "train", "eval", "seg_fix"])
        cols = []
        for K in range(1, 8):
            parts = [pd.read_parquet(f) for f in sorted((OUT / "runs").glob(f"{args.name}_{farm}_k{K}_s0_f*_anchors.parquet"))]
            if not parts:
                raise FileNotFoundError(f"no anchor scores for {farm} k={K}")
            cols.append(pd.concat(parts).set_index("row")["p"].rename(f"r{K}"))
        R = pd.concat(cols, axis=1).dropna()
        a = A.loc[R.index]
        H = 7 * BINS_PER_DAY
        sel = (a["train"] & a["eval"] & (a["k"] > BINS_PER_DAY) & (a["k"] <= H) & a["key"].isin(logged)
               & (a["seg_fix"] == "")).to_numpy()
        Rk = np.fmax.accumulate(R.to_numpy(float)[sel], axis=1)
        true_q = a["k"].to_numpy()[sel]
        pd_day = np.diff(np.c_[np.zeros(len(Rk)), Rk], axis=1)                        # mass per day
        pmf = np.repeat(pd_day / BINS_PER_DAY, BINS_PER_DAY, axis=1)                  # uniform inside a day
        cdf = np.cumsum(pmf, 1) / np.maximum(pmf.sum(1, keepdims=True), 1e-12)
        q10, q50, q90 = [(cdf < q).sum(1) + 1 for q in (0.1, 0.5, 0.9)]
        rows.append({"farm": farm, "model": "CatBoost 15 min (k=1..7, seed 0)", "anchors": int(sel.sum()),
                     "events": int(a.loc[sel, "key"].nunique()),
                     "median |error| (h)": np.median(np.abs(q50 - true_q)) / 4,
                     "uniform curve: median |error| (h)": np.median(np.abs(336.5 - true_q)) / 4,
                     "true onset day = predicted median day": np.mean((q50 - 1) // BINS_PER_DAY == (true_q - 1) // BINS_PER_DAY),
                     "80% interval coverage": np.mean((q10 <= true_q) & (true_q <= q90)),
                     "80% interval width (h)": np.median(q90 - q10) / 4})
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    lstm = pd.read_csv(LSTM / "results_timing_15min.csv").assign(note="LSTM session, daily anchors")
    pd.concat([out.assign(note="this run, 15-minute anchors"), lstm], ignore_index=True).round(2).to_csv(
        Path(args.out) / "results_timing.csv", index=False)


# --------------------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("features")
    pf.add_argument("--data", default=str(PREPARED))
    pf.add_argument("--out", default=str(OUT))
    pf.add_argument("--farms", default="A,B,C")
    pf.add_argument("--workers", type=int, default=4)
    pc = sub.add_parser("cv")
    pc.add_argument("--out", default=str(OUT))
    pc.add_argument("--farm", required=True)
    pc.add_argument("--horizon", type=int, default=7)
    pc.add_argument("--seeds", default="0")
    pc.add_argument("--folds", default="all")
    pc.add_argument("--name", default="cb15")
    pc.add_argument("--features", default="", help="JSON {farm: [feature names]} to restrict the columns")
    pc.add_argument("--threads", type=int, default=10)
    pc.add_argument("--shap-rows", type=int, default=3000)
    pc.add_argument("--no-shap", action="store_true")
    pc.add_argument("--save-anchor-scores", action="store_true")
    pr = sub.add_parser("report")
    pr.add_argument("--out", default=str(OUT))
    pr.add_argument("--farms", default="A,B,C")
    pr.add_argument("--models", default="CatBoost 15 min=cb15",
                    help="comma list label=run_name of runs/<run_name>_<farm>_k7.pkl")
    pr.add_argument("--n-boot", type=int, default=N_BOOT)
    pr.add_argument("--suffix", default="")
    ps = sub.add_parser("select")
    ps.add_argument("--out", default=str(OUT))
    ps.add_argument("--farms", default="A,B,C")
    ps.add_argument("--run", default="cb15")
    ps.add_argument("--top", type=int, default=150)
    ps.add_argument("--max-features", type=int, default=100)
    pk = sub.add_parser("kumo-eval")
    pk.add_argument("--kumo", required=True, help="folder with kumo_<farm>_scores.parquet")
    pk.add_argument("--farms", default="A,B,C")
    pk.add_argument("--name", default="kumo")
    pk.add_argument("--seed", type=int, default=0)
    pt = sub.add_parser("timing")
    pt.add_argument("--out", default=str(OUT))
    pt.add_argument("--farms", default="A,B,C")
    pt.add_argument("--name", default="cb15")
    args = p.parse_args()
    {"timing": cmd_timing, "features": cmd_features, "cv": cmd_cv, "report": cmd_report, "select": cmd_select,
     "kumo-eval": cmd_kumo_eval}[args.cmd](args)


if __name__ == "__main__":
    main()
