"""
# Repair scheduler

Picks one repair day per failing turbine for a park served by a single repair crew: at most one
repair per day, each before the turbine's predicted failure day, preferring the days when the
wind (and so the lost output) is lowest.

The search is exact. Days are few (a week), so a dynamic program over the set of days already
taken finds the optimum in a handful of states instead of settling for a greedy answer. The
objective is lexicographic:

1. Save as many turbines as possible.
2. When some cannot be saved, give up the ones that would have produced the least.
3. Minimise the output lost while turbines are down: `weight * wind speed` of the repair day,
   which sends the highest-output turbine to the calmest day.
4. Prefer earlier days on ties.

A turbine predicted to fail on day `n` is repaired on day `n - 1` at the latest. One predicted
to fail today (day 0) can only be repaired today.

The following can be imported from this module:
- `MAX_HORIZON_DAYS`
- `RepairRequest`
- `RepairSlot`
- `fill_wind`
- `schedule_repairs`
"""

from collections.abc import Sequence
from dataclasses import dataclass

from smarthack.constants import WIND_FORECAST_DAYS


@dataclass(frozen=True)
class RepairRequest:
    """
    A turbine that needs a repair slot.

    `failure_day` counts days from today: 0 is today, 3 is in three days.
    `weight` is the output the turbine is expected to produce, in any unit as long as all the
    requests of one call share it. Use 1.0 for all when the output is unknown.
    """

    turbine_id: int
    failure_day: int
    weight: float = 1.0


@dataclass(frozen=True)
class RepairSlot:
    """
    The repair day chosen for one turbine.

    `day` is None when no day before the predicted failure was left free. `wind_speed` is the
    forecast wind of the chosen day, or None when it is unscheduled or no forecast was known.
    """

    turbine_id: int
    day: int | None
    wind_speed: float | None


#: The search tracks which days are taken as a bit set, so its size doubles with each day.
#: 16 days is the longest forecast Open-Meteo gives and still searches instantly.
MAX_HORIZON_DAYS = 16

#: Sort key of a partial plan: turbines left out, their total weight, output lost, sum of days.
_Score = tuple[int, float, float, int]


def fill_wind(daily_wind: Sequence[float | None], horizon: int) -> list[float]:
    """
    Turn the forecast into one number per day, filling the days it does not cover.

    :param daily_wind: Forecast wind speed per day from today, None where unknown.
    :param horizon: How many days to return.

    :returns wind: `horizon` values; gaps get the mean of the known days, or 0.0 if none is known.
    """
    known = [w for w in daily_wind[:horizon] if w is not None]
    fill = sum(known) / len(known) if known else 0.0
    padded = list(daily_wind[:horizon]) + [None] * (horizon - len(daily_wind[:horizon]))
    return [fill if w is None else w for w in padded]


def schedule_repairs(
    requests: list[RepairRequest],
    daily_wind: Sequence[float | None],
    horizon_days: int = WIND_FORECAST_DAYS,
) -> dict[int, RepairSlot]:
    """
    Choose a repair day for each turbine, at most one repair per day.

    :param requests: Turbines to repair, each with its predicted failure day and weight.
    :param daily_wind: Forecast wind speed per day from today (index 0 is today), None where
        unknown. May be empty, then every turbine gets its earliest free day.
    :param horizon_days: Number of days a repair can be planned in. Defaults to the forecast span.

    :returns schedule: One `RepairSlot` per turbine id, `day=None` for those left unscheduled.
    :raises ValueError: On a non-positive horizon, a negative weight or a repeated turbine id.
    """
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"horizon_days must be 1 to {MAX_HORIZON_DAYS}, got {horizon_days}")
    if len({r.turbine_id for r in requests}) != len(requests):
        raise ValueError("turbine ids in requests must be unique")
    if any(r.weight < 0 for r in requests):
        raise ValueError("weights must not be negative")

    wind = fill_wind(daily_wind, horizon_days)
    known_days = {d for d in range(min(len(daily_wind), horizon_days)) if daily_wind[d] is not None}

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

    _, best_picks = min(states.values(), key=lambda s: s[0])
    return {
        req.turbine_id: RepairSlot(
            turbine_id=req.turbine_id,
            day=day,
            wind_speed=wind[day] if day is not None and day in known_days else None,
        )
        for req, day in zip(ordered, best_picks, strict=True)
    }


__all__ = ["MAX_HORIZON_DAYS", "RepairRequest", "RepairSlot", "fill_wind", "schedule_repairs"]
