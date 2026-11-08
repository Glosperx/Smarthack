"""
# Leaderboard filter

Reads `data/index.json` of the Hugging Face Space `multimodalart/jev-decision-index` and lists
the models small enough for a laptop, ranked by the Full score (`scores.balanced_skill`: 60%
private same-skill tests, 40% private new-domain tasks).

Download the file first, then run from `experiments/decision_model`:

    uv run python -I -m decision_model.leaderboard out/index.json --max-params 9.6

The following can be imported from this module:
- `SmallModel`
- `small_models`
- `main`
"""

import argparse
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SmallModel:
    """One leaderboard row, with the fields the shortlist needs."""

    engine: str
    name: str
    params_b: float
    full: float | None
    public: float | None
    kind: str | None
    technique: str | None
    weights: str | None
    ece: float | None
    latency_median_ms: float | None


def _row(model: Mapping[str, Any]) -> SmallModel:
    """Turn one entry of `models` into a `SmallModel`."""
    meta = model.get("meta") or {}
    scores = model.get("scores") or {}
    return SmallModel(
        engine=model["engine"],
        name=model["name"],
        params_b=round((meta.get("served_params") or 0) / 1e9, 2),
        full=scores.get("balanced_skill"),
        public=scores.get("public_skill"),
        kind=meta.get("kind"),
        technique=meta.get("technique"),
        weights=meta.get("weights_repo") or meta.get("model_url") or meta.get("served_checkpoint"),
        ece=(model.get("calibration") or {}).get("ece"),
        latency_median_ms=(model.get("latency") or {}).get("median"),
    )


def small_models(index: Mapping[str, Any], max_params_b: float) -> list[SmallModel]:
    """
    Keep the models with at most `max_params_b` billion served parameters, best Full score first.

    :param index: Parsed `data/index.json`.
    :param max_params_b: Largest size kept, in billions of parameters.

    :returns models: Models with a known size within the limit; those without a Full score last.
    """
    rows = [_row(m) for m in index.get("models", [])]
    kept = [r for r in rows if 0 < r.params_b <= max_params_b]
    return sorted(kept, key=lambda r: (r.full is None, -(r.full or 0.0), r.engine))


def main(argv: list[str] | None = None) -> int:
    """
    Print the filtered leaderboard as JSON lines.

    :param argv: Command-line arguments; None reads `sys.argv`.

    :returns status: 0 on success.
    """
    parser = argparse.ArgumentParser(description="Small models of the Jev Decision Index.")
    parser.add_argument("index", type=Path, help="Path to the Space's data/index.json.")
    parser.add_argument("--max-params", type=float, default=9.6, help="Billions of parameters.")
    args = parser.parse_args(argv)
    index = json.loads(args.index.read_text(encoding="utf-8"))
    for row in small_models(index, args.max_params):
        print(json.dumps(asdict(row), ensure_ascii=False))
    return 0


__all__ = ["SmallModel", "small_models", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
