"""
Build the Kaggle kernel folder (`kaggle/`) from `care_fault_forecast.py`.

The notebook embeds the script with `%%writefile`, so the kernel needs no extra upload,
only the CARE dataset attached. Push it with:

    kaggle kernels push -p fault_detection/kaggle --accelerator NvidiaTeslaT4
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
OWNER = "teodorapanait"
SLUG = "care-fault-forecast-lstm-attention"
DATASET = "azizkasimov/wind-turbine-scada-data-for-early-fault-detection"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n")}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n")}


def main() -> None:
    script = (HERE / "care_fault_forecast.py").read_text()
    cells = [
        md("""
# CARE fault forecast: BiLSTM + attention, 15-minute windows, 7-day horizon

Dataset: *Wind Turbine SCADA Data For Early Fault Detection* (CARE to Compare): 95 datasets,
36 turbines, 3 wind farms, 44 labelled faults.

At every anchor ("now") the model outputs a hazard for each of the next **672 windows of
15 minutes** (7 days). From it: **P(fault within 7 days)** (the binary "needs maintenance"
alarm, scored by recall) and **the most likely 15-minute window** with an 80% interval.

Cross-validation is grouped by turbine (5 folds). On **GPU T4 x2** two training processes
run in parallel, one per GPU (folds 0,2,4 and 1,3).
"""),
        code("""
import os, sys, subprocess, time, torch
print(sys.version.split()[0], "| torch", torch.__version__, "| CPUs", os.cpu_count())
for i in range(torch.cuda.device_count()):
    print(f"cuda:{i}", torch.cuda.get_device_name(i))
assert torch.cuda.is_available(), "no GPU: Settings > Accelerator > GPU T4 x2"
"""),
        code("%%writefile care_fault_forecast.py\n" + script),
        md("## 1. Prepare: CSV (10 min) -> 15-minute arrays, normalized per turbine on its train part"),
        code("""
!python care_fault_forecast.py prepare --input /kaggle/input --out /tmp/care15 --workers {os.cpu_count()}
"""),
        md("## 2. Quick check: one short epoch on fold 0 (fails fast if anything is wrong)"),
        code("""
!python care_fault_forecast.py train --data /tmp/care15 --out /tmp/smoke --device cuda:0 \\
    --folds 0 --epochs 1 --epoch-samples 4000 --eval-stride 32
"""),
        md("## 3. Full cross-validation, one process per GPU"),
        code("""
n_gpu = torch.cuda.device_count()
plan = {0: "0,2,4", 1: "1,3"} if n_gpu >= 2 else {0: "all"}
procs = {}
for gpu, folds in plan.items():
    log = open(f"/kaggle/working/train_gpu{gpu}.log", "w")
    procs[gpu] = subprocess.Popen(
        [sys.executable, "care_fault_forecast.py", "train", "--data", "/tmp/care15",
         "--out", "/kaggle/working/runs", "--device", f"cuda:{gpu}", "--folds", folds],
        stdout=log, stderr=subprocess.STDOUT)
t0 = time.time()
while any(p.poll() is None for p in procs.values()):
    time.sleep(120)
    for gpu in plan:
        lines = open(f"/kaggle/working/train_gpu{gpu}.log").read().strip().splitlines()
        print(f"[{(time.time() - t0) / 60:5.1f} min] gpu{gpu}: {lines[-1] if lines else ''}", flush=True)
for gpu, p in procs.items():
    print(f"gpu{gpu} exit code {p.returncode}")
    if p.returncode:
        print(open(f"/kaggle/working/train_gpu{gpu}.log").read()[-5000:])
assert all(p.returncode == 0 for p in procs.values())
"""),
        md("## 4. Out-of-fold report: recall, timing error, weekly report"),
        code("""
!python care_fault_forecast.py report --runs /kaggle/working/runs --out /kaggle/working/report
from IPython.display import Markdown, display
display(Markdown(open("/kaggle/working/report/report.md").read()))
"""),
    ]
    nb = {"cells": cells, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    out = HERE / "kaggle"
    out.mkdir(exist_ok=True)
    (out / "care_lstm_attention.ipynb").write_text(json.dumps(nb, indent=1))
    (out / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{OWNER}/{SLUG}",
        "title": "CARE fault forecast LSTM attention",
        "code_file": "care_lstm_attention.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": False,
        "dataset_sources": [DATASET],
        "competition_sources": [],
        "kernel_sources": [],
    }, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
