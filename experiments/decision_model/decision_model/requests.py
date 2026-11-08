"""
# Decision requests

Builds the two dispatch-agent decisions as System One requests: a `state` plus one typed
`choice` question, so any Jev-style model returns a probability for every option.

Decision 1 asks whether the wind power model (ML2) is worth calling for a park; decision 2
asks which alert channel a turbine gets. Each comes in two variants: `fara_politica` explains
what the fields mean and asks the question; `cu_politica` also states the rule of today, to see
whether a model applies a written policy.

The following can be imported from this module:
- `ML2_OPTIONS`
- `CHANNEL_OPTIONS`
- `VARIANTS`
- `ORDERS`
- `build_request`
"""

from collections.abc import Mapping
from typing import Any

ML2_OPTIONS: dict[str, str] = {
    "da": "Call the wind power model: the repair crew must choose which turbine to repair first.",
    "nu": "Do not call it: no two turbines compete for the crew in the same interval.",
}

CHANNEL_OPTIONS: dict[str, str] = {
    "doar_email": "Send the maintenance crew an email work order only.",
    "email_si_apel": "Send the email and also phone the on-call crew now.",
    "nimic": "Send no alert.",
}

FIELDS = (
    "days_to_failure is ML1's predicted number of days until the turbine fails (8 means no "
    "failure is predicted within the 7-day horizon); fault_probability is ML1's probability "
    "that the turbine fails within 7 days."
)

ML2_QUESTION = (
    "One maintenance crew serves this park and repairs at most one turbine per day. "
    + FIELDS
    + " Only turbines with health_status CRITICAL or WARNING need a repair, and turbines of "
    "other parks have their own crews. Should the agent call the wind power model to decide "
    "which turbine of this park to repair first?"
)
ML2_POLICY = (
    " Policy: call it when at least two turbines of this park that need a repair have failure "
    "days at most conflict_window_days apart, counting whole days (days_to_failure rounded "
    "down); otherwise do not call it."
)

CHANNEL_QUESTION = (
    "How should the maintenance crew be alerted about this turbine? "
    + FIELDS
    + " health_status is the condition assessment (NORMAL, WATCH, WARNING, CRITICAL)."
)
CHANNEL_POLICY = (
    " Policy: email and phone call when health_status is CRITICAL, or days_to_failure is at "
    "most 2, or fault_probability is at least 0.70. Otherwise email only when health_status is "
    "WARNING or WATCH, or fault_probability is at least 0.30. Otherwise no alert."
)

VARIANTS = ("fara_politica", "cu_politica")

# Three runs per request: option orders. The third order of decision 1 repeats the first, so it
# also checks that the same request gives the same answer twice.
ORDERS: dict[str, list[list[str]]] = {
    "ml2": [["da", "nu"], ["nu", "da"], ["da", "nu"]],
    "channel": [
        ["doar_email", "email_si_apel", "nimic"],
        ["email_si_apel", "nimic", "doar_email"],
        ["nimic", "doar_email", "email_si_apel"],
    ],
}


def _ordered(options: Mapping[str, str], order: list[str]) -> dict[str, str]:
    """
    Reorder the options of a question.

    :param options: Option key to description.
    :param order: Keys in the order to present them.

    :returns options: The same options in the requested order.
    :raises ValueError: When `order` is not a permutation of the option keys.
    """
    if sorted(order) != sorted(options):
        raise ValueError(f"order {order} is not a permutation of {list(options)}")
    return {key: options[key] for key in order}


def build_request(
    decision: str,
    state: Mapping[str, Any],
    variant: str = "fara_politica",
    order_index: int = 0,
) -> dict[str, Any]:
    """
    Build the System One request for one scenario.

    :param decision: "ml2" (decision 1) or "channel" (decision 2).
    :param state: The scenario state; it is sent as is.
    :param variant: "fara_politica" or "cu_politica".
    :param order_index: Which of the three option orders to use.

    :returns request: {"state", "questions"} with one `choice` question keyed `q`.
    :raises ValueError: For an unknown decision or variant.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    if decision == "ml2":
        options, question, policy = ML2_OPTIONS, ML2_QUESTION, ML2_POLICY
    elif decision == "channel":
        options, question, policy = CHANNEL_OPTIONS, CHANNEL_QUESTION, CHANNEL_POLICY
    else:
        raise ValueError(f"unknown decision {decision!r}")
    instructions = question + (policy if variant == "cu_politica" else "")
    criteria = _ordered(options, ORDERS[decision][order_index])
    return {
        "state": dict(state),
        "questions": {"q": {"type": "choice", "instructions": instructions, "criteria": criteria}},
    }


__all__ = ["ML2_OPTIONS", "CHANNEL_OPTIONS", "VARIANTS", "ORDERS", "build_request"]
