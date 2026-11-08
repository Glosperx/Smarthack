from typing import Any

import pytest

from decision_model.leaderboard import small_models
from decision_model.smoke import latency_summary


def _model(engine: str, params: float | None, full: float | None) -> dict[str, Any]:
    return {
        "engine": engine,
        "name": engine.upper(),
        "meta": {"served_params": params, "kind": "full fine-tune", "model_url": f"hf/{engine}"},
        "scores": {} if full is None else {"balanced_skill": full, "public_skill": full + 5},
        "calibration": {"ece": 0.05},
        "latency": {"median": 40.0},
    }


def test_small_models_filters_by_size_and_ranks_by_full_score() -> None:
    index = {
        "models": [
            _model("big", 31e9, 70.0),
            _model("mid", 4.2e9, 50.0),
            _model("best", 8.9e9, 60.0),
            _model("unscored", 2e9, None),
            _model("unknown-size", None, 99.0),
        ]
    }

    rows = small_models(index, max_params_b=9.6)

    assert [r.engine for r in rows] == ["best", "mid", "unscored"]
    assert rows[0].params_b == 8.9
    assert rows[0].weights == "hf/best"
    assert rows[0].public == 65.0


def test_latency_summary_in_milliseconds() -> None:
    summary = latency_summary([0.010, 0.030, 0.020])

    assert summary == {"median_ms": 20.0, "p95_ms": 30.0, "max_ms": 30.0}


def test_latency_summary_needs_timings() -> None:
    with pytest.raises(ValueError):
        latency_summary([])
