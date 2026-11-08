"""
# Repair scheduler (copy)

The agent's exact repair scheduler (`smarthack/services/agent/repair_scheduler.py` on `dev`),
copied because this experiment has its own venv and cannot import `smarthack`. Single crew, at
most one repair per day, each before the turbine's failure day; the objective is lexicographic:

1. save as many turbines as possible;
2. when some cannot be saved, give up the ones that would have produced the least;
3. minimise the output lost while turbines are down, `weight * wind speed` of the repair day;
4. prefer earlier days on ties.

A turbine predicted to fail on day `n` is repaired on day `n - 1` at the latest; one failing on
day 0 only on day 0.

The following can be imported from this module:
- `RepairRequest`
- `schedule_repairs`
"""

from collections.abc import Sequence
from dataclasses import dataclass

_Score = tuple[int, float, float, int]


@dataclass(frozen=True)
class RepairRequest:
    """A turbine that needs a repair slot: failure day from today and expected output."""

    turbine_id: int
    failure_day: int
    weight: float = 1.0


def _fill_wind(daily_wind: Sequence[float | None], horizon: int) -> list[float]:
    """One wind value per day; gaps get the mean of the known days, or 0.0 if none is known."""
    known = [w for w in daily_wind[:horizon] if w is not None]
    fill = sum(known) / len(known) if known else 0.0
    padded = list(daily_wind[:horizon]) + [None] * (horizon - len(daily_wind[:horizon]))
    return [fill if w is None else w for w in padded]


def schedule_repairs(
    requests: list[RepairRequest], daily_wind: Sequence[float | None], horizon_days: int = 7
) -> dict[int, int | None]:
    """
    Choose a repair day for each turbine, at most one repair per day (copy of the agent's).

    :param requests: Turbines to repair, each with its failure day and weight.
    :param daily_wind: Forecast wind speed per day from today.
    :param horizon_days: Days a repair can be planned in.

    :returns schedule: Repair day per turbine id, None for those left unscheduled.
    """
    wind = _fill_wind(daily_wind, horizon_days)
    ordered = sorted(requests, key=lambda r: (-r.weight, r.failure_day, r.turbine_id))
    states: dict[int, tuple[_Score, tuple[int | None, ...]]] = {0: ((0, 0.0, 0.0, 0), ())}
    for req in ordered:
        last_day = min(max(req.failure_day - 1, 0), horizon_days - 1)
        advanced: dict[int, tuple[_Score, tuple[int | None, ...]]] = {}
        for taken, (score, picks) in states.items():
            options: list[int | None] = [None] + [
                d for d in range(last_day + 1) if not taken & (1 << d)
            ]
            for day in options:
                if day is None:
                    new_taken = taken
                    new_score: _Score = (score[0] + 1, score[1] + req.weight, score[2], score[3])
                else:
                    new_taken = taken | (1 << day)
                    new_score = (
                        score[0],
                        score[1],
                        score[2] + req.weight * wind[day],
                        score[3] + day,
                    )
                current = advanced.get(new_taken)
                if current is None or new_score < current[0]:
                    advanced[new_taken] = (new_score, picks + (day,))
        states = advanced
    _, best = min(states.values(), key=lambda s: s[0])
    return {req.turbine_id: day for req, day in zip(ordered, best, strict=True)}


__all__ = ["RepairRequest", "schedule_repairs"]
