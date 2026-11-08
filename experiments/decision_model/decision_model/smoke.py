"""
# Smoke test

Loads one GLiDE-family checkpoint from a local directory, sends the two dispatch decisions and
reports load time, peak memory and the latency of one decision. Nothing leaves the machine:
the model directory must already be downloaded.

Run from `experiments/decision_model`:

    uv run python -I -m decision_model.smoke models/GLiDE-0.4B --device mps

The `glide` inference package ships inside the model directory, so that directory is put on
`sys.path` before it is imported, as the model card does.

The following can be imported from this module:
- `latency_summary`
- `main`
"""

import argparse
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time
from typing import Any

from decision_model.requests import build_request

# Offline from here on: a missing file must fail instead of being fetched.
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def latency_summary(seconds: list[float]) -> dict[str, float]:
    """
    Summarise per-decision wall times.

    :param seconds: One wall time per decision, in seconds.

    :returns summary: Median, p95 and max in milliseconds, rounded to 0.1 ms.
    :raises ValueError: When no timings are given.
    """
    if not seconds:
        raise ValueError("no timings")
    ms = sorted(s * 1000 for s in seconds)
    p95 = ms[min(len(ms) - 1, round(0.95 * (len(ms) - 1)))]
    return {
        "median_ms": round(statistics.median(ms), 1),
        "p95_ms": round(p95, 1),
        "max_ms": round(ms[-1], 1),
    }


def _peak_rss_gb() -> float:
    """Peak resident memory of this process so far; macOS reports ru_maxrss in bytes."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9


def _mps_driver_gb() -> float | None:
    """Memory the Metal driver holds for this process, or None when MPS is not in use."""
    import torch

    if not torch.backends.mps.is_available():
        return None
    return float(torch.mps.driver_allocated_memory()) / 1e9


def _sync(device: str) -> None:
    """Wait for queued GPU work, so the wall time covers the whole decision."""
    import torch

    if device == "mps":
        torch.mps.synchronize()


def _requests() -> list[dict[str, Any]]:
    """One request per decision, with values the current rules decide clearly."""
    ml2_state = {
        "park_id": "wind_farm_a",
        "conflict_window_days": 1,
        "turbines": [
            {
                "turbine_id": 10,
                "park_id": "wind_farm_a",
                "health_status": "WARNING",
                "days_to_failure": 1.4,
                "fault_probability": 0.6,
            },
            {
                "turbine_id": 11,
                "park_id": "wind_farm_a",
                "health_status": "CRITICAL",
                "days_to_failure": 2.1,
                "fault_probability": 0.7,
            },
        ],
    }
    channel_state = {
        "park_id": "wind_farm_a",
        "turbine_id": 10,
        "health_status": "WARNING",
        "days_to_failure": 4.5,
        "fault_probability": 0.42,
        "suspected_failure": "gearbox bearing",
    }
    return [build_request("ml2", ml2_state), build_request("channel", channel_state)]


def main(argv: list[str] | None = None) -> int:
    """
    Run the smoke test and print a JSON report.

    :param argv: Command-line arguments; None reads `sys.argv`.

    :returns status: 0 on success.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("model_dir", type=Path, help="Local GLiDE checkpoint directory.")
    parser.add_argument("--device", default="mps", choices=["mps", "cpu"])
    parser.add_argument("--repeats", type=int, default=30, help="Timed decisions per request.")
    parser.add_argument("--out", type=Path, default=None, help="Also write the report here.")
    args = parser.parse_args(argv)

    model_dir = args.model_dir.resolve()
    sys.path.insert(0, str(model_dir))
    from glide import Glide
    import torch

    rss_before = _peak_rss_gb()
    t0 = time.perf_counter()
    model = Glide.from_pretrained(str(model_dir), device=args.device, vision=False)
    _sync(args.device)
    load_s = time.perf_counter() - t0
    driver_after_load = _mps_driver_gb() if args.device == "mps" else None

    report: dict[str, Any] = {
        "model_dir": model_dir.name,
        "device": args.device,
        "torch": torch.__version__,
        "load_s": round(load_s, 2),
        "peak_rss_gb_before_load": round(rss_before, 2),
        "mps_driver_gb_after_load": driver_after_load and round(driver_after_load, 2),
        "decisions": [],
    }
    driver_peak = driver_after_load or 0.0
    for request in _requests():
        (key,) = request["questions"]
        first_t0 = time.perf_counter()
        answer = model.decide(request["state"], request["questions"])
        _sync(args.device)
        first_s = time.perf_counter() - first_t0
        timings = []
        for _ in range(args.repeats):
            t = time.perf_counter()
            model.decide(request["state"], request["questions"])
            _sync(args.device)
            timings.append(time.perf_counter() - t)
            driver_peak = max(driver_peak, _mps_driver_gb() or 0.0)
        report["decisions"].append(
            {
                "question": key,
                "answer": answer["answers"][key],
                "input_tokens": answer["usage"]["input_tokens"],
                "first_call_ms": round(first_s * 1000, 1),
                **latency_summary(timings),
            }
        )
    report["peak_rss_gb"] = round(_peak_rss_gb(), 2)
    report["mps_driver_gb_peak"] = round(driver_peak, 2) if args.device == "mps" else None

    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


__all__ = ["latency_summary", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
