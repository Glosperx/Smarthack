"""
Build the Kaggle kernel folder (`kaggle_kumo/`) for the Kumo Tabular run.

The notebook embeds the three scripts and the small inputs (fold table, timeline table,
shortlist) as base64, attaches only the public CARE dataset, rebuilds the 15-minute anchors and
features on Kaggle, and runs `care_kumo_tabular.py` on the GPU. Nothing from the local cache
other than those three small tables is uploaded.

    python fault_detection/build_kumo_kernel.py --mode smoke     (farm A, fold 0, final fit, timing)
    python fault_detection/build_kumo_kernel.py --mode full
    kaggle kernels push -p fault_detection/kaggle_kumo --accelerator NvidiaTeslaT4
"""

import argparse
import base64
import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
CACHE = ROOT / "dataset" / "wind_turbine_scada_fault" / "cache"
OWNER = "teodorapanait"
SLUG = "care-kumo-tabular-15min"
DATASET = "azizkasimov/wind-turbine-scada-data-for-early-fault-detection"
W = "/kaggle/working"
K_CACHE = f"{W}/dataset/wind_turbine_scada_fault/cache"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n")}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text.strip("\n")}


def embed(src: Path, dst: str) -> dict:
    b64 = base64.b64encode(src.read_bytes()).decode()
    return code(f"import base64, os\nos.makedirs(os.path.dirname('{dst}'), exist_ok=True)\n"
                f"open('{dst}', 'wb').write(base64.b64decode('{b64}'))")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    p.add_argument("--size", default="large")
    p.add_argument("--estimators", type=int, default=1, help="1 chosen after the smoke test (192 rows/s at 4)")
    p.add_argument("--perm-rows", type=int, default=1000)
    args = p.parse_args()
    run = (f"--only-folds 0 --no-inner --perm-rows 0 --size {args.size}" if args.mode == "smoke"
           else f"--size {args.size} --estimators {args.estimators} --perm-rows {args.perm_rows}")
    plan = {0: "A"} if args.mode == "smoke" else {0: "C", 1: "A,B"}
    cells = [
        md(f"""
# CARE fault forecast: NVIDIA Kumo Tabular on the CatBoost 15-minute shortlist ({args.mode})

Same anchors, censored target (onset within 7 days), folds and inner groups as the CatBoost
15-minute model of the Smarthack repository. Kumo is in-context: each fit is a sample of the
training turbines' anchors as context (at most 100 columns, 10,240 rows per estimator, inside
the model's training range), the query is the anchors to score. Scores are evaluated locally
with the baseline protocol.
"""),
        code("""
import os, sys, subprocess, torch
print(sys.version.split()[0], "| torch", torch.__version__, "| CPUs", os.cpu_count())
assert torch.cuda.is_available(), "no GPU"
print([torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())])
"""),
        code("!pip install -q structured-data-models 2>&1 | tail -3\nimport sdm; print('sdm', getattr(sdm, '__version__', '?'))"),
    ]
    for name in ("care_fault_forecast.py", "care_catboost_15min.py", "care_kumo_tabular.py"):
        cells.append(embed(HERE / name, f"{W}/fault_detection/{name}"))
    cells += [
        embed(CACHE / "lstm_attention" / "meta.parquet", f"{K_CACHE}/lstm_attention/meta.parquet"),
        embed(CACHE / "catboost_baseline" / "cv_folds.parquet", f"{K_CACHE}/catboost_baseline/cv_folds.parquet"),
        embed(CACHE / "catboost_15min" / "shortlist.json", f"{K_CACHE}/catboost_15min/shortlist.json"),
        md("## 1. Kumo API check on random data (output layout, device)"),
        code("""
import numpy as np, pandas as pd, sdm, time
rng = np.random.default_rng(0)
df = pd.DataFrame(rng.normal(size=(600, 5)), columns=list("abcde"))
df["target"] = pd.Categorical((df.a + rng.normal(size=600) > 0).astype(int))
st = sdm.infer_stypes(df, overrides={**{c: "numerical" for c in "abcde"}, "target": "categorical"})
print(st)
t = sdm.TableTensor.from_pandas(df=df, stypes=st, device="cuda")
m = sdm.models.KumoTabular(task="classification", size="small", device="cuda")
with torch.autocast("cuda", dtype=torch.float16):
    out = m(x_context=t[:400].drop_columns("target"), y_context=t[:400, "target"], x_query=t[400:].drop_columns("target"))
print(type(out), getattr(out, "shape", None))
print(out.to_pandas().head() if hasattr(out, "to_pandas") else out[:5])
sys.path.insert(0, "/kaggle/working/fault_detection")
from care_kumo_tabular import to_prob
from sklearn.metrics import roc_auc_score
p1 = to_prob(out); print("p[:5]", p1[:5], "AUC on the toy task", roc_auc_score(df.target[400:].astype(int), p1))
m.fit(x=t[:400].drop_columns("target"), y=t[:400, "target"], num_estimators=2)
print("fit/predict path", to_prob(m.predict(t[400:].drop_columns("target")))[:5]); m.clear()
"""),
        md("## 2. 15-minute arrays and anchor features (same code as locally)"),
        code(f"""
def sh(cmd):
    r = subprocess.run(cmd, shell=True, cwd="{W}", capture_output=True, text=True)
    print(r.stdout[-3000:], r.stderr[-3000:])
    assert r.returncode == 0, f"failed: {{cmd}}"
sh(f"python fault_detection/care_fault_forecast.py prepare --input /kaggle/input --out /tmp/prepared "
   f"--workers {{os.cpu_count()}} | tail -3")
sh(f"python fault_detection/care_catboost_15min.py features --data /tmp/prepared --out /tmp/cb15 --workers {{os.cpu_count()}}")
"""),
        md("## 3. Kumo Tabular"),
        code(f"""
import time
common = ("python fault_detection/care_kumo_tabular.py --data /tmp/cb15 "
          "--folds {K_CACHE}/catboost_baseline/cv_folds.parquet --shortlist {K_CACHE}/catboost_15min/shortlist.json "
          "--out {W}/kumo {run}")
n_gpu = torch.cuda.device_count()
plan = {plan}
plan = plan if n_gpu >= 2 else {{0: ",".join(plan.values())}}
procs = {{}}
for gpu, farms in plan.items():
    log = open(f"{W}/kumo_gpu{{gpu}}.log", "w")
    procs[gpu] = subprocess.Popen(common + f" --farms {{farms}}", shell=True, cwd="{W}", stdout=log,
                                  stderr=subprocess.STDOUT, env={{**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu)}})
t0 = time.time()
while any(p.poll() is None for p in procs.values()):
    time.sleep(300)
    for gpu in plan:
        lines = [l for l in open(f"{W}/kumo_gpu{{gpu}}.log").read().splitlines() if l.startswith("[")]
        print(f"[{{(time.time() - t0) / 60:5.1f}} min] gpu{{gpu}}: {{lines[-1] if lines else ''}}", flush=True)
for gpu, p in procs.items():
    print(f"gpu{{gpu}} exit {{p.returncode}}")
    if p.returncode:
        print(open(f"{W}/kumo_gpu{{gpu}}.log").read()[-4000:])
assert all(p.returncode == 0 for p in procs.values())
"""),
        code(f"!rm -rf {W}/fault_detection {W}/dataset; ls -la {W}/kumo"),
    ]
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    out = HERE / "kaggle_kumo"
    out.mkdir(exist_ok=True)
    (out / "care_kumo_tabular.ipynb").write_text(json.dumps(nb, indent=1))
    (out / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{OWNER}/{SLUG}", "title": "CARE Kumo Tabular 15min", "code_file": "care_kumo_tabular.ipynb",
        "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": True,
        "enable_internet": True, "dataset_sources": [DATASET], "competition_sources": [], "kernel_sources": [],
    }, indent=1))
    print("wrote", out, "mode", args.mode)


if __name__ == "__main__":
    main()
