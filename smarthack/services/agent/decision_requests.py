"""
# Decision requests

Builds the two questions the dispatch agent puts to the local decision model as System One
requests: a `state` plus one typed `choice` question whose options the model scores.

- **Repair plan.** The code works out the candidate plans and writes each in words; the model
  picks one. The options are named `plan_A`, `plan_B`, ... in an order shuffled from the park and
  turbine ids: the same situation always gives the same request, and no plan keeps a fixed letter.
- **Alert channel.** One request per turbine. The policy of the rule is written into the question,
  built from the same constants the rule reads: without it a model has to guess the thresholds.

The question texts are the ones the model was tested with (`experiments/decision_model`); change
one and the test results no longer describe what runs.

The following can be imported from this module:
- `CHANNEL_OPTIONS`
- `CHANNEL_POLICY`
- `CHANNEL_QUESTION`
- `DecisionRequest`
- `PLAN_INSTRUCTIONS`
- `build_channel_request`
- `build_plan_request`
"""

from collections.abc import Mapping, Sequence
import random
from typing import Any, NamedTuple

from smarthack.constants import (
    CHANNEL_CALL_DAYS,
    CHANNEL_CALL_PROBABILITY,
    CHANNEL_EMAIL_PROBABILITY,
    NO_FAILURE_DAYS,
)
from smarthack.schemas.dispatch import AlertChannel
from smarthack.services.agent.failure_overlap import item_failure_day, lead_time_days
from smarthack.services.agent.repair_plans import Plan, describe_plan
from smarthack.services.agent.repair_scheduler import RepairRequest

PLAN_INSTRUCTIONS = (
    "One maintenance crew serves this park and repairs at most one turbine per day. The options "
    "are complete repair plans, worked out from the forecast. Choose the plan that saves the "
    "most turbines; if several save the same number, choose the one with the smallest output "
    "lost on repair days. Which plan should the crew follow?"
)

_FIELDS = (
    "days_to_failure is ML1's predicted number of days until the turbine fails (8 means no "
    "failure is predicted within the 7-day horizon); fault_probability is ML1's probability "
    "that the turbine fails within 7 days."
)

CHANNEL_QUESTION = (
    "How should the maintenance crew be alerted about this turbine? "
    + _FIELDS
    + " health_status is the condition assessment (NORMAL, WATCH, WARNING, CRITICAL)."
)

CHANNEL_POLICY = (
    " Policy: email and phone call when health_status is CRITICAL, or days_to_failure is at "
    f"most {CHANNEL_CALL_DAYS:g}, or fault_probability is at least {CHANNEL_CALL_PROBABILITY:.2f}. "
    "Otherwise email only when health_status is WARNING or WATCH, or fault_probability is at "
    f"least {CHANNEL_EMAIL_PROBABILITY:.2f}. Otherwise no alert."
)

#: The channel options in the order the model was tested with, each with its description.
CHANNEL_OPTIONS: dict[str, str] = {
    AlertChannel.EMAIL.value: "Send the maintenance crew an email work order only.",
    AlertChannel.VOICE_CALL.value: "Send the email and also phone the on-call crew now.",
    AlertChannel.NONE.value: "Send no alert.",
}


class DecisionRequest(NamedTuple):
    """One question for the decision model: the facts, the question and the options."""

    state: dict[str, Any]
    instructions: str
    options: dict[str, str]


def build_plan_request(
    park_id: str,
    turbines: Sequence[Mapping[str, Any]],
    requests: Sequence[RepairRequest],
    plans: Sequence[Plan],
    wind: Sequence[float],
) -> tuple[DecisionRequest, dict[str, Plan]]:
    """
    Build the request that asks the model to pick one of the candidate plans.

    :param park_id: The park the crew serves.
    :param turbines: The failing turbines, with `health_status`, `fault_probability` and
        `projected_mwh_7d`.
    :param requests: The scheduler requests of those turbines, whose weights are the outputs.
    :param plans: The distinct candidate plans.
    :param wind: Wind speed per day from today, no gaps (see `fill_wind`).

    :returns built: The request, and each option name's plan.
    """
    weights = {r.turbine_id: r.weight for r in requests}
    state = {
        "park_id": park_id,
        "wind_forecast": [
            {"day": day, "wind_speed_m_s": round(speed, 1)} for day, speed in enumerate(wind)
        ],
        "turbines": [
            {
                "turbine_id": int(t["turbine_id"]),
                "health_status": str(t.get("health_status", "NORMAL")),
                "failure_day": _state_failure_day(t),
                "fault_probability": round(float(t.get("fault_probability") or 0.0), 2),
                "projected_mwh_7d": round(weights[int(t["turbine_id"])], 1),
            }
            for t in turbines
        ],
    }
    shuffled = list(plans)
    seed = f"{park_id}:{','.join(str(i) for i in sorted(weights))}"
    random.Random(seed).shuffle(shuffled)
    by_name = {f"plan_{chr(ord('A') + i)}": plan for i, plan in enumerate(shuffled)}
    options = {name: describe_plan(plan, weights, wind) for name, plan in by_name.items()}
    return DecisionRequest(state, PLAN_INSTRUCTIONS, options), by_name


def _state_failure_day(turbine: Mapping[str, Any]) -> int:
    """
    The failure day shown to the model: the real one, or the "none predicted" value.

    :param turbine: A triage item.

    :returns day: The whole failure day, or `NO_FAILURE_DAYS`.
    """
    day = item_failure_day(turbine)
    return NO_FAILURE_DAYS if day is None else day


def build_channel_request(park_id: str, item: Mapping[str, Any]) -> DecisionRequest:
    """
    Build the request that asks the model how to alert the crew about one turbine.

    :param park_id: The park the turbine belongs to.
    :param item: The turbine's triage item.

    :returns request: The request, with the policy of the rule in the question.
    """
    state = {
        "park_id": park_id,
        "turbine_id": int(item["turbine_id"]),
        "health_status": str(item.get("health_status", "NORMAL")),
        "days_to_failure": min(lead_time_days(item), float(NO_FAILURE_DAYS)),
        "fault_probability": float(item.get("fault_probability") or 0.0),
        "suspected_failure": str(item.get("suspected_failure", "Unknown")),
    }
    return DecisionRequest(state, CHANNEL_QUESTION + CHANNEL_POLICY, dict(CHANNEL_OPTIONS))


__all__ = [
    "CHANNEL_OPTIONS",
    "CHANNEL_POLICY",
    "CHANNEL_QUESTION",
    "DecisionRequest",
    "PLAN_INSTRUCTIONS",
    "build_channel_request",
    "build_plan_request",
]
