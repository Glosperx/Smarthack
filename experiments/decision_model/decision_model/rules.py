"""
# Rules of today (baseline)

The two decisions exactly as the dispatch agent takes them on `dev`, copied because this
experiment has its own venv and cannot import `smarthack`:

- decision 1, call ML2: `node_triage_park` keeps the park's own turbines whose health status
  needs a repair (CRITICAL or WARNING), then `node_check_failure_overlap` calls ML2 when two of
  them fail at most `CONFLICT_WINDOW_DAYS` whole days apart
  (`smarthack/services/agent/graph.py`, `failure_overlap.py`);
- decision 2, alert channel: `classify_alert_channel` in `smarthack/services/agent/prompts.py`.

`tests/test_rules.py` pins the copied behaviour on the cases that define it.

The following can be imported from this module:
- `CONFLICT_WINDOW_DAYS`
- `REPAIR_STATUSES`
- `failure_day`
- `overlapping_failures`
- `rule_ml2`
- `rule_channel`
"""

from collections.abc import Mapping, Sequence
from typing import Any

CONFLICT_WINDOW_DAYS = 1
REPAIR_STATUSES = ("CRITICAL", "WARNING")
WIND_FORECAST_DAYS = 7.0


def failure_day(days_to_failure: float) -> int:
    """
    Whole day, counted from today, on which the turbine is due to fail (copy of the agent's).

    :param days_to_failure: Predicted lead time in days; 0.8 means within today.

    :returns day: 0 for today, 1 for tomorrow, and so on; never negative.
    """
    return max(int(days_to_failure), 0)


def overlapping_failures(failure_days: Mapping[int, int], window_days: int) -> set[int]:
    """
    Turbines whose failure day is within `window_days` of another turbine's (copy of the agent's).

    :param failure_days: Failure day of each turbine, keyed by turbine id.
    :param window_days: Largest gap in days that still counts as the same interval.

    :returns turbine_ids: Ids that overlap with at least one other turbine.
    """
    ordered = sorted(failure_days.items(), key=lambda item: (item[1], item[0]))
    overlapping: set[int] = set()
    for (id_a, day_a), (id_b, day_b) in zip(ordered, ordered[1:], strict=False):
        if day_b - day_a <= window_days:
            overlapping.update((id_a, id_b))
    return overlapping


def rule_ml2(park_id: str, turbines: Sequence[Mapping[str, Any]], window_days: int) -> str:
    """
    Decision 1 as the agent takes it: triage to the park's turbines that need a repair, then
    look for two failure days within the window.

    :param park_id: Park whose crew is being scheduled.
    :param turbines: Turbines with `turbine_id`, `park_id`, `health_status` and `days_to_failure`.
    :param window_days: Largest gap in days that still counts as the same interval.

    :returns option: "da" when ML2 is called, else "nu".
    """
    failing = [
        t
        for t in turbines
        if str(t.get("park_id", park_id)) == str(park_id)
        and str(t.get("health_status", "NORMAL")).upper() in REPAIR_STATUSES
    ]
    days = {
        int(t["turbine_id"]): failure_day(float(t.get("days_to_failure", WIND_FORECAST_DAYS)))
        for t in failing
    }
    return "da" if overlapping_failures(days, window_days) else "nu"


def rule_channel(health_status: str, days_to_failure: float, fault_probability: float) -> str:
    """
    Decision 2 as `classify_alert_channel` takes it, with the agent's channels renamed to the
    option keys of this experiment.

    :param health_status: Assessed health state (CRITICAL, WARNING, WATCH, NORMAL, ...).
    :param days_to_failure: Days remaining until functional failure.
    :param fault_probability: 7-day failure likelihood.

    :returns option: "email_si_apel" (VOICE_CALL), "doar_email" (EMAIL) or "nimic" (NONE).
    """
    status = health_status.upper()
    if status == "CRITICAL" or days_to_failure <= 2.0 or fault_probability >= 0.70:
        return "email_si_apel"
    if status in ("WARNING", "WATCH") or fault_probability >= 0.30:
        return "doar_email"
    return "nimic"


__all__ = [
    "CONFLICT_WINDOW_DAYS",
    "REPAIR_STATUSES",
    "failure_day",
    "overlapping_failures",
    "rule_ml2",
    "rule_channel",
]
