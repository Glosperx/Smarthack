"""
# CARE fault forecast: NVIDIA Kumo Tabular (in-context) on the CatBoost 15-minute shortlist

Runs on a CUDA GPU (Kaggle), after `care_fault_forecast.py prepare` and
`care_catboost_15min.py features` have built the anchors and features there.

Same anchors, target (onset within 7 days, censored), folds (`cv_folds.parquet`, `per_farm`)
and inner groups as `care_catboost_15min.py cv`. Kumo is not trained: for every fit the
"context" is a sample of the training turbines' labelled anchors and the "query" is the anchors
to score. Per outer fold: 3 inner fits (context from the other inner groups, query the held-out
group, for the threshold and the isotonic calibration done locally) and 1 final fit (context
from all training turbines, query the test turbines).

Context size: Kumo Tabular was trained on tables of up to 60,000 rows and 100 columns and NVIDIA
warns that accuracy may degrade far outside those ranges; no hard inference limit is
documented. So: at most 100 shortlist columns, and `--context-rows` rows per estimator
(default 10,240, the largest size of the second training stage), `--estimators` random context
samples averaged.

Permutation importance (not KernelSHAP): on the final model of each fold, on `--perm-rows`
labelled test anchors, the drop of the anchor-level ROC-AUC when one column is shuffled.

Output (`--out`): `kumo_<farm>_scores.parquet` (row, stage, fold, group, p) and
`kumo_<farm>_perm.csv`, `kumo_<farm>_timing.csv`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from care_catboost_15min import auc_fast, inner_groups, target  # noqa: E402


def to_prob(out) -> np.ndarray:
    """
    P(class 1) from Kumo's output table, whatever the column layout turned out to be.

    :param out: The `TableTensor` returned by the model.

    :returns p: Probabilities of the positive class.
    """
    if hasattr(out, "to_pandas"):                    # TableTensor: one probability column per class
        df = out.to_pandas()
    elif hasattr(out, "detach"):                     # a plain torch tensor (rows, classes)
        a = out.detach().float().cpu().numpy()
        return a[:, -1] if a.ndim == 2 else a
    else:
        df = pd.DataFrame(out)
    cols = [str(c) for c in df.columns]
    for c in ("1", "1.0", "prob_1", "target_1", "p1"):
        if c in cols:
            return df[df.columns[cols.index(c)]].to_numpy(float)
    num = df.select_dtypes("number")
    if num.shape[1] == 2:
        return num.iloc[:, 1].to_numpy(float)
    if num.shape[1] == 1:
        return num.iloc[:, 0].to_numpy(float)
    raise ValueError(f"unknown Kumo output columns: {cols}")


class Kumo:
    """Thin wrapper: one context, many queries, P(onset within 7 d)."""

    def __init__(self, size: str, estimators: int, seed: int):
        import sdm  # structured-data-models
        import torch

        self.sdm, self.torch = sdm, torch
        self.model = sdm.models.KumoTabular(task="classification", size=size, device="cuda")
        self.model.eval()
        self.estimators = estimators
        self.batch = 4096
        self.gen = torch.Generator(device="cuda").manual_seed(seed)

    def table(self, X: np.ndarray, names: list[str], y: np.ndarray | None = None):
        df = pd.DataFrame(X, columns=names)
        over = {c: "numerical" for c in names}       # Kumo Tabular takes numerical inputs only
        if y is not None:
            df["target"] = pd.Categorical(y.astype(int))
            over["target"] = "categorical"
        return self.sdm.TableTensor.from_pandas(df=df, stypes=self.sdm.infer_stypes(df, overrides=over),
                                                device="cuda")

    def fit(self, X: np.ndarray, y: np.ndarray, names: list[str]) -> None:
        t = self.table(X, names, y)
        # same autocast as predict: the cached context keys/values must match the query dtype
        with self.torch.no_grad(), self.torch.autocast("cuda", dtype=self.torch.float16):
            self.model.fit(x=t.drop_columns("target"), y=t["target"], num_estimators=self.estimators,
                           generator=self.gen)

    def predict(self, X: np.ndarray, names: list[str]) -> np.ndarray:
        """Query in batches; memory grows with batch x context, so halve the batch on OOM."""
        out, i = [], 0
        with self.torch.no_grad(), self.torch.autocast("cuda", dtype=self.torch.float16):
            while i < len(X):
                try:
                    out.append(to_prob(self.model.predict(self.table(X[i:i + self.batch], names))))
                    i += self.batch
                except self.torch.OutOfMemoryError:
                    self.torch.cuda.empty_cache()
                    assert self.batch > 64, "out of memory even at 64 queries"
                    self.batch //= 2
                    print(f"  OOM: query batch -> {self.batch}", flush=True)
        return np.concatenate(out) if out else np.zeros(0)

    def clear(self) -> None:
        self.model.clear()


def context_rows(rows: np.ndarray, y: np.ndarray, n: int, pos_share: float, rng) -> np.ndarray:
    """
    Sample the context: positives up to `pos_share` of `n`, the rest negatives.

    :param rows: Candidate anchor indices (finite target).
    :param y: Target per anchor.
    :param n: Context rows.
    :param pos_share: Largest share of positives.
    :param rng: Generator.

    :returns rows: The sample, sorted.
    """
    pos, neg = rows[y[rows] == 1], rows[y[rows] == 0]
    n_pos = min(len(pos), int(n * pos_share))
    n_neg = min(len(neg), n - n_pos)
    return np.sort(np.r_[rng.choice(pos, n_pos, replace=False), rng.choice(neg, n_neg, replace=False)])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="folder with anchors_<farm>.parquet, X_<farm>.npy, features_<farm>.json")
    p.add_argument("--folds", required=True, help="cv_folds.parquet")
    p.add_argument("--shortlist", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--farms", default="A,B,C")
    p.add_argument("--only-folds", default="all")
    p.add_argument("--size", default="large", choices=["small", "medium", "large"])
    p.add_argument("--estimators", type=int, default=4)
    p.add_argument("--context-rows", type=int, default=10_240)
    p.add_argument("--pos-share", type=float, default=0.25)
    p.add_argument("--perm-rows", type=int, default=5000)
    p.add_argument("--no-inner", action="store_true", help="skip the inner fits (timing tests only)")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    folds = pd.read_parquet(args.folds)
    short = json.loads(Path(args.shortlist).read_text())
    kumo = Kumo(args.size, args.estimators, args.seed)
    for farm in args.farms.split(","):
        A = pd.read_parquet(Path(args.data) / f"anchors_{farm}.parquet")
        X_all = np.load(Path(args.data) / f"X_{farm}.npy", mmap_mode="r")
        names_all = json.loads((Path(args.data) / f"features_{farm}.json").read_text())
        names = short[farm][:100]
        X = np.ascontiguousarray(X_all[:, [names_all.index(c) for c in names]])
        del X_all
        y = target(A, 7)
        turb = A["turbine"].to_numpy()
        evl = A["eval"].to_numpy()
        lab = np.flatnonzero(np.isfinite(y))
        fo = folds[(folds["scheme"] == "per_farm") & (folds["farm"] == farm) & (folds["seed"] == args.seed)]
        fold = pd.Series(turb).map(fo.set_index("turbine")["fold"]).to_numpy()
        rng = np.random.default_rng(args.seed)
        scores, timing, perm = [], [], []
        wanted = np.unique(fold) if args.only_folds == "all" else [int(f) for f in args.only_folds.split(",")]
        for k in wanted:
            tr = fold != k
            stages = [] if args.no_inner else [
                ("inner", gi, tr & ~np.isin(turb, g), tr & np.isin(turb, g) & evl)
                for gi, g in enumerate(inner_groups(np.unique(turb[tr]), args.seed))]
            stages.append(("final", -1, tr, (fold == k) & evl))
            for stage, gi, ctx_mask, q_mask in stages:
                t0 = time.time()
                ctx = context_rows(lab[ctx_mask[lab]], y, args.context_rows, args.pos_share, rng)
                q = np.flatnonzero(q_mask)
                kumo.fit(X[ctx], y[ctx], names)
                t_fit = time.time() - t0
                pq = kumo.predict(X[q], names)
                t_pred = time.time() - t0 - t_fit
                scores.append(pd.DataFrame({"row": q, "stage": stage, "fold": k, "group": gi,
                                            "p": pq.astype(np.float32)}))
                timing.append(dict(farm=farm, fold=int(k), stage=stage, group=gi, context=len(ctx),
                                   queries=len(q), seconds_fit=t_fit, seconds_predict=t_pred))
                print(f"[{farm} fold {k} {stage} {gi}] context {len(ctx):,}, queries {len(q):,}, "
                      f"fit {t_fit:.0f}s, predict {t_pred:.0f}s ({len(q) / max(t_pred, 1e-9):,.0f} rows/s)",
                      flush=True)
                if stage == "final" and args.perm_rows:
                    te = np.flatnonzero((fold == k) & evl & np.isfinite(y))
                    if 0 < y[te].sum() < len(te):
                        te = np.sort(rng.choice(te, min(args.perm_rows, len(te)), replace=False))
                        base = auc_fast(kumo.predict(X[te], names), y[te])
                        Xp = X[te].copy()
                        for j, c in enumerate(names):
                            col = Xp[:, j].copy()
                            Xp[:, j] = rng.permutation(col)
                            perm.append(dict(farm=farm, fold=int(k), feature=c, base_auc=base,
                                             auc_drop=base - auc_fast(kumo.predict(Xp, names), y[te])))
                            Xp[:, j] = col
                        print(f"[{farm} fold {k}] permutation importance on {len(te):,} anchors, "
                              f"base AUC {base:.3f} ({time.time() - t0:.0f}s since fit)", flush=True)
                kumo.clear()
            pd.concat(scores).to_parquet(out / f"kumo_{farm}_scores.parquet")
            pd.DataFrame(timing).to_csv(out / f"kumo_{farm}_timing.csv", index=False)
            if perm:
                pd.DataFrame(perm).to_csv(out / f"kumo_{farm}_perm.csv", index=False)


if __name__ == "__main__":
    main()
