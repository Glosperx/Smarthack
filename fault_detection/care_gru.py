"""Small GRU on daily deviation sequences for the CARE fault target (used by notebooks/care_gru.ipynb).

One job = one outer fold of one farm, one input variant and one fold seed. Inside the job, exactly like the CatBoost
baseline: three inner fits (each holds out one inner turbine group) give the number of epochs (median of their best
epochs) and the inner out-of-fold scores of the training turbines; the final fit on all training turbines scores the
test turbines. Every fit is a self-supervised pretraining (predict the next day's inputs, on negative days only)
followed by fine-tuning on the label with an auxiliary next-day loss. Inputs are preprocessed inside each fit, on its
own training rows only.
"""

from __future__ import annotations

import copy
import warnings

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch import nn

DEFAULTS = dict(window=30, hidden=16, dropout=0.4, lr=1e-3, weight_decay=1e-2, batch=128, noise=0.1,
                pretrain_epochs=15, max_epochs=30, patience=5, aux_weight=0.1, n_pca=16, net_seeds=(0, 1))


def window_index(pos: np.ndarray, length: int) -> np.ndarray:
    """Row indices of the `length` days ending at each row (same timeline); -1 where the timeline has not started."""
    n = len(pos)
    back = np.arange(length - 1, -1, -1)
    idx = np.arange(n)[:, None] - back[None, :]
    idx[back[None, :] > pos[:, None]] = -1
    return idx


class GRUNet(nn.Module):
    """One-layer GRU; a linear decoder predicts the next day's inputs, a linear head gives the logit at the last day."""

    def __init__(self, d_in: int, hidden: int, dropout: float):
        super().__init__()
        self.gru = nn.GRU(d_in, hidden, batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.dec = nn.Linear(hidden, d_in)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x):
        out, _ = self.gru(x)
        out = self.drop(out)
        return self.dec(out), self.head(out[:, -1]).squeeze(-1)


def fit_preprocess(Xraw, log_cols, fit_rows, neg_rows, pca_cols, n_pca):
    """Fit the preprocessing on training rows only; returns the parameters (saved with a production model)."""
    X = Xraw.astype(np.float64).copy()
    X[:, log_cols] = np.log1p(np.clip(X[:, log_cols], 0, None))
    keep = np.setdiff1d(np.arange(X.shape[1]), pca_cols) if len(pca_cols) else np.arange(X.shape[1])
    A = X[:, keep]
    mu, sd = np.nanmean(A[fit_rows], 0), np.nanstd(A[fit_rows], 0)
    params = dict(log_cols=np.asarray(log_cols, int), keep=keep, pca_cols=np.asarray(pca_cols, int),
                  mu=np.where(np.isfinite(mu), mu, 0.0), sd=np.where(np.isfinite(sd) & (sd > 1e-9), sd, 1.0))
    if len(pca_cols):
        P = X[:, pca_cols]
        pm, ps = np.nanmean(P[neg_rows], 0), np.nanstd(P[neg_rows], 0)
        pm, ps = np.where(np.isfinite(pm), pm, 0.0), np.where(np.isfinite(ps) & (ps > 1e-9), ps, 1.0)
        Pz = np.nan_to_num((P - pm) / ps, nan=0.0)
        _, _, vt = np.linalg.svd(Pz[neg_rows], full_matrices=False)
        comp = vt[:n_pca]
        cs = (Pz @ comp.T)[fit_rows].std(0)
        params.update(pca_mu=pm, pca_sd=ps, pca_comp=comp, pca_scale=np.where(cs > 1e-9, cs, 1.0))
    return params


def apply_preprocess(Xraw, params):
    """Apply fitted preprocessing: inputs (float32) and the mask of days with any missing input."""
    X = Xraw.astype(np.float64).copy()
    X[:, params["log_cols"]] = np.log1p(np.clip(X[:, params["log_cols"]], 0, None))
    blocks = [np.nan_to_num((X[:, params["keep"]] - params["mu"]) / params["sd"], nan=0.0)]
    if len(params["pca_cols"]):
        Pz = np.nan_to_num((X[:, params["pca_cols"]] - params["pca_mu"]) / params["pca_sd"], nan=0.0)
        blocks.append((Pz @ params["pca_comp"].T) / params["pca_scale"])
    miss = ~np.isfinite(Xraw[:, params["keep"]]).all(1)   # a day with any missing input: not a pretraining target
    return np.hstack(blocks).astype(np.float32), miss


def preprocess(Xraw, log_cols, fit_rows, neg_rows, pca_cols, n_pca):
    """log1p on |rz| columns, standardise on the fit rows, optional PCA block; missing values become 0 (the mean)."""
    return apply_preprocess(Xraw, fit_preprocess(Xraw, log_cols, fit_rows, neg_rows, pca_cols, n_pca))


def gather(Z, miss, idx, rows):
    """Input windows for some anchor rows, plus the mask of real (not padded, not missing) days."""
    w = idx[rows]
    Zp = np.vstack([Z, np.zeros((1, Z.shape[1]), np.float32)])
    mp = np.r_[miss, True]
    w = np.where(w < 0, len(Z), w)
    return torch.from_numpy(Zp[w]), torch.from_numpy(~mp[w])


def _aux_loss(dec, x, ok):
    """Next-day prediction error on the real days of the window."""
    m = (ok[:, :-1] & ok[:, 1:]).unsqueeze(-1).float()
    err = ((dec[:, :-1] - x[:, 1:]) ** 2) * m
    return err.sum() / (m.sum() * x.shape[-1]).clamp(min=1.0)


def _batches(n, batch, rng):
    order = rng.permutation(n)
    return [order[i:i + batch] for i in range(0, n, batch)]


def train_one(Z, miss, idx, y, w, fit_rows, neg_rows, cfg, seed, val_rows=None, epochs=None):
    """Pretrain then fine-tune one network; returns the per-epoch states (if validating), val AUCs and curves."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    net = GRUNet(Z.shape[1], cfg["hidden"], cfg["dropout"])
    opt = torch.optim.AdamW(net.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    xn, okn = gather(Z, miss, idx, neg_rows)
    for _ in range(cfg["pretrain_epochs"]):
        net.train()
        for b in _batches(len(neg_rows), cfg["batch"], rng):
            x = xn[b] + cfg["noise"] * torch.randn_like(xn[b])
            dec, _ = net(x)
            loss = _aux_loss(dec, xn[b], okn[b])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
    xf, okf = gather(Z, miss, idx, fit_rows)
    yf, wf = torch.from_numpy(y[fit_rows].astype(np.float32)), torch.from_numpy(w[fit_rows].astype(np.float32))
    if val_rows is not None:
        xv, _ = gather(Z, miss, idx, val_rows)
        yv = y[val_rows]
    bce = nn.BCEWithLogitsLoss(reduction="none")
    n_ep = epochs if epochs is not None else cfg["max_epochs"]
    states, val_auc, curve = [], [], []
    best, since = -np.inf, 0
    for ep in range(n_ep):
        net.train()
        tot = 0.0
        for b in _batches(len(fit_rows), cfg["batch"], rng):
            x = xf[b] + cfg["noise"] * torch.randn_like(xf[b])
            dec, logit = net(x)
            loss = (bce(logit, yf[b]) * wf[b]).sum() / wf[b].sum() + cfg["aux_weight"] * _aux_loss(dec, xf[b], okf[b])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            tot += float(loss.detach()) * len(b)
        row = {"epoch": ep + 1, "train_loss": tot / len(fit_rows)}
        if val_rows is not None:
            yt = y[fit_rows]
            row["train_auc"] = roc_auc_score(yt, predict(net, xf)) if 0 < yt.sum() < len(yt) else np.nan
            sv = predict(net, xv)
            a = roc_auc_score(yv, sv) if 0 < yv.sum() < len(yv) else np.nan
            row["val_auc"] = a
            val_auc.append(a)
            states.append(copy.deepcopy(net.state_dict()))
            if np.isfinite(a) and a > best + 1e-4:
                best, since = a, 0
            else:
                since += 1
            if since >= cfg["patience"]:
                break
        curve.append(row)
    return net, states, val_auc, curve


def predict(net, x, batch=2048):
    """Logits of the last day of each window."""
    net.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            out.append(net(x[i:i + batch])[1].numpy())
    return np.concatenate(out) if out else np.zeros(0)


def run_job(job: dict) -> dict:
    """One outer fold: inner fits (epochs and inner out-of-fold scores), then the final fit on the test turbines.

    `job` holds the arrays (Xraw, y, w, usable, turb, fold, pos), the outer fold `k`, the inner turbine groups, the
    input columns of every fit (`cols` keyed by inner group index or "final"), the log1p columns, the PCA columns,
    and the settings.
    """
    torch.set_num_threads(job.get("threads", 2))
    warnings.filterwarnings("ignore", category=RuntimeWarning)   # all-missing columns become 0
    cfg = dict(DEFAULTS, **job.get("cfg", {}))
    Xraw, y, w, usable, turb, fold = job["Xraw"], job["y"], job["w"], job["usable"], job["turb"], job["fold"]
    lab = np.isfinite(y)
    yz = np.nan_to_num(y)
    idx = window_index(job["pos"], cfg["window"])
    te, tr = fold == job["k"], fold != job["k"]
    n = len(y)
    oof, test = np.full(n, np.nan), np.full(n, np.nan)
    best_epochs, curves, inner = [], [], []

    def prep(key, fit_mask):
        cols = job["cols"][key]
        pca = job["pca_cols"][key]
        allc = np.r_[cols, pca].astype(int)
        logc = np.flatnonzero(np.isin(allc, job["log_cols"]))
        pcac = np.arange(len(cols), len(allc)) if len(pca) else np.zeros(0, int)
        fit_rows = np.flatnonzero(fit_mask & lab & usable)
        neg_rows = np.flatnonzero(fit_mask & usable & (yz == 0) & lab)
        Z, miss = preprocess(Xraw[:, allc], logc, fit_rows, neg_rows, pcac, cfg["n_pca"])
        return Z, miss, fit_rows, neg_rows

    for gi, g in enumerate(job["groups"]):
        va = tr & np.isin(turb, g)
        fit_m = tr & ~va
        if yz[fit_m & lab & usable].sum() == 0 or yz[va & lab & usable].sum() == 0:
            continue
        Z, miss, fit_rows, neg_rows = prep(gi, fit_m)
        val_rows = np.flatnonzero(va & lab & usable)
        all_va = np.flatnonzero(va & usable)
        per_seed = []
        for s in cfg["net_seeds"]:
            net, states, vauc, curve = train_one(Z, miss, idx, yz, w, fit_rows, neg_rows, cfg, 1000 * job["seed"] + s,
                                                 val_rows=val_rows)
            per_seed.append((net, states, vauc))
            curves += [dict(c, group=gi, net_seed=s) for c in curve]
            best_epochs.append(int(np.nanargmax(vauc)) + 1 if np.isfinite(vauc).any() else len(vauc))
        inner.append((gi, all_va, Z, miss, per_seed))
    n_star = int(np.clip(np.median(best_epochs), 2, cfg["max_epochs"])) if best_epochs else cfg["max_epochs"]
    for gi, all_va, Z, miss, per_seed in inner:
        x, _ = gather(Z, miss, idx, all_va)
        scores = []
        for net, states, _ in per_seed:
            net.load_state_dict(states[min(n_star, len(states)) - 1])
            scores.append(predict(net, x))
        oof[all_va] = np.mean(scores, 0)
    Z, miss, fit_rows, neg_rows = prep("final", tr)
    te_rows = np.flatnonzero(te & usable)
    x, _ = gather(Z, miss, idx, te_rows)
    scores = []
    for s in cfg["net_seeds"]:
        net, _, _, curve = train_one(Z, miss, idx, yz, w, fit_rows, neg_rows, cfg, 1000 * job["seed"] + s, epochs=n_star)
        scores.append(predict(net, x))
        curves += [dict(c, group="final", net_seed=s) for c in curve]
    test[te_rows] = np.mean(scores, 0)
    return dict(farm=job["farm"], variant=job["variant"], seed=job["seed"], k=job["k"], oof=oof, test=test,
                n_epochs=n_star, best_epochs=best_epochs, curves=curves)


def ml1_scores(feat, farm, model_dir, pos):
    """Score daily rows with the saved ML1 blend (CatBoost + GRU groups + PCA 16) of one farm.

    `feat` is the daily feature table of the baseline (notebooks/care_catboost_baseline.ipynb, sections 1 to 5), sorted
    by timeline and day; `pos` is each row's position in its timeline (0 = first day). Returns the blended score, the
    calibrated risk (k = 7) and the alarm flags at the saved thresholds.
    """
    import json
    from pathlib import Path

    from catboost import CatBoostClassifier

    model_dir = Path(model_dir)
    c = json.loads((model_dir / "ml1_contract.json").read_text())["farms"][farm]
    X = feat[c["catboost_features"]].to_numpy(np.float32)
    p_cb = np.mean([CatBoostClassifier().load_model(str(model_dir / fn)).predict_proba(X)[:, 1]
                    for fn in c["catboost_files"]], axis=0)
    z_cb = np.log(np.clip(p_cb, 1e-6, 1 - 1e-6) / np.clip(1 - p_cb, 1e-6, 1))
    pre = dict(np.load(model_dir / c["gru_preprocess_file"]))
    Z, miss = apply_preprocess(feat[c["gru_inputs"]].to_numpy(np.float32), pre)
    g = c["gru"]
    idx = window_index(np.asarray(pos), g["window"])
    x, _ = gather(Z, miss, idx, np.arange(len(feat)))
    states = torch.load(model_dir / c["gru_file"], weights_only=True)
    logits = []
    for st in states:
        net = GRUNet(Z.shape[1], g["hidden"], g["dropout"])
        net.load_state_dict(st)
        logits.append(predict(net, x))
    z_gru = np.mean(logits, 0)
    b = c["blend"]
    score = 0.5 * (z_cb - b["cb_mu"]) / b["cb_sd"] + 0.5 * (z_gru - b["gru_mu"]) / b["gru_sd"]
    risk = np.interp(score, c["calibration"]["x"], c["calibration"]["y"])
    alarms = {name: score >= thr for name, thr in c["thresholds"].items()}
    return score, risk, alarms
