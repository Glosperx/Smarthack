"""
# Model decisions

Where the dispatch agent asks the local decision model, checks what it answers and falls back to
the rule. Two decisions, each with the same shape: the code prepares the options, the model scores
them, the code decides how far to trust the score.

- **Repair plan** (`choose_plan`): the model picks among the plans the code worked out. The pick is
  refused when it saves fewer turbines than the exact optimum. A pick that saves as many turbines
  but loses more output is accepted: telling it apart from a better one would mean overriding the
  model every time it differs, and then it would decide nothing.
- **Alert channel** (`choose_channel`): the model picks among call-and-email, email, and nothing.
  A CRITICAL turbine always gets the call, whatever the model says.

Two modes, from `DECISION_MODEL_MODE`. In `umbra` (shadow) the rule or optimum decides and the
model's choice is only recorded beside it, so the logs show where it would differ before it is
allowed to. In `activ` the model decides.

Any `DecisionModelError` (server down, too slow, malformed answer) falls back to the rule or
optimum and tells the caller the model is down, so the rest of the run does not wait on it again.

Each question to the model is also traced (see `tracing`) as one observation whose output is that
record, so its duration in Langfuse is the model's latency.

Every decision returns a record with the same data that is logged: the options, the probabilities,
the model's pick, what was used, who decided (`source`) and the latency.

The following can be imported from this module:
- `ChannelDecision`
- `PlanDecision`
- `choose_channel`
- `choose_plan`
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
import time
from typing import Any

from smarthack.clients.decision_client import DecisionClient, DecisionModelError
from smarthack.constants import WIND_FORECAST_DAYS
from smarthack.schemas.dispatch import AlertChannel
from smarthack.services.agent import tracing
from smarthack.services.agent.decision_requests import build_channel_request, build_plan_request
from smarthack.services.agent.failure_overlap import lead_time_days
from smarthack.services.agent.prompts import classify_alert_channel
from smarthack.services.agent.repair_plans import (
    Plan,
    build_requests,
    candidate_plans,
    has_output_estimate,
    plan_output_lost,
    plan_saved,
)
from smarthack.services.agent.repair_scheduler import fill_wind

logger = logging.getLogger(__name__)

#: The mode in which the model decides; any other mode only records its choice.
_ACTIVE_MODE = "activ"

#: Name of the served model, shown on its `generation` observations in Langfuse.
_MODEL_NAME = "jeffan-4b"


def _usage(client: DecisionClient) -> dict[str, Any]:
    """
    Tell Langfuse how many tokens the last question cost, when the server counted them.

    Jeffan reads the prompt in one forward pass and writes no text, so only input tokens exist;
    it runs locally, so there is no cost.

    :param client: The client that just got an answer.

    :returns fields: `{"usage_details": {...}}` for `Trace.update`, or `{}` when unknown.
    """
    tokens = getattr(client, "last_prompt_tokens", None)
    if isinstance(tokens, int) and not isinstance(tokens, bool):
        return {"usage_details": {"input": tokens, "output": 0}}
    return {}


@dataclass(frozen=True)
class PlanDecision:
    """
    The repair plan to follow.

    `chosen` maps turbine id to repair day. `record` is what was logged. `model_down` is True when
    the model failed during this decision.
    """

    chosen: Plan
    record: dict[str, Any]
    model_down: bool


@dataclass(frozen=True)
class ChannelDecision:
    """
    The channel to alert a turbine's crew on.

    `channel` is the one to use. `record` is what was logged. `model_down` is True when the model
    failed during this decision.
    """

    channel: AlertChannel
    record: dict[str, Any]
    model_down: bool


def _rounded(probabilities: Mapping[str, float]) -> dict[str, float]:
    """
    Shorten probabilities for the log.

    :param probabilities: Option key to probability.

    :returns rounded: The same, to three decimals.
    """
    return {key: round(value, 3) for key, value in probabilities.items()}


def _argmax(probabilities: Mapping[str, float]) -> str:
    """
    Pick the most probable option; the first one wins a tie.

    :param probabilities: Option key to probability, in presentation order.

    :returns key: The option with the highest probability.
    """
    return max(probabilities, key=lambda key: probabilities[key])


def choose_plan(
    park_id: str,
    turbines: Sequence[Mapping[str, Any]],
    daily_wind: Sequence[float | None],
    client: DecisionClient | None,
    mode: str,
    model_down: bool = False,
) -> PlanDecision:
    """
    Decide which repair plan the crew follows.

    The model is not asked when it is off or already down, when every candidate plan is the same,
    when there is no wind forecast (plans would differ in nothing the model can see), or when no
    turbine has an output estimate (the plans could not be compared on output lost).

    :param park_id: The park the crew serves.
    :param turbines: The failing turbines, `projected_mwh_7d` set when the power model ran.
    :param daily_wind: Forecast wind speed per day from today, None where unknown; may be empty.
    :param client: The decision model client, or None when the model is off.
    :param mode: `"activ"` lets the model decide; anything else only records its pick.
    :param model_down: True when the model already failed earlier in this run.

    :returns decision: The plan to follow, the record of how it was chosen, and whether the model
        failed.
    """
    requests = build_requests(turbines)
    plans = candidate_plans(requests, daily_wind)
    optimum = plans[0]
    record: dict[str, Any] = {
        "park": park_id,
        "mode": mode,
        "options": {},
        "probabilities": None,
        "model_pick": None,
        "chosen": "optimum",
        "source": "rule",
        "reason": None,
        "latency_ms": None,
    }

    if client is None:
        record["reason"] = "disabled"
    elif model_down:
        record["reason"] = "model_down"
    elif not any(speed is not None for speed in daily_wind):
        record["reason"] = "no_wind_forecast"
    elif not has_output_estimate(turbines):
        record["reason"] = "no_output_estimate"
    elif len(plans) < 2:
        record["reason"] = "one_plan"
    if client is None or record["reason"] is not None:
        level = logging.DEBUG if record["reason"] == "disabled" else logging.INFO
        logger.log(
            level, "Park %s repair plan: optimum, model not asked (%s)", park_id, record["reason"]
        )
        return PlanDecision(optimum, record, False)

    wind = fill_wind(daily_wind, WIND_FORECAST_DAYS)
    weights = {r.turbine_id: r.weight for r in requests}
    request, by_name = build_plan_request(park_id, turbines, requests, plans, wind)
    record["options"] = dict(request.options)
    with tracing.model_call(
        "jev.repair_plan",
        {"mode": mode, "state": request.state, "options": request.options},
        model=_MODEL_NAME,
    ) as span:
        started = time.perf_counter()
        try:
            probabilities = client.choice(request.state, request.instructions, request.options)
        except DecisionModelError as exc:
            record.update(
                reason="error",
                source="rule_fallback" if mode == _ACTIVE_MODE else "rule",
                latency_ms=round(1000 * (time.perf_counter() - started)),
            )
            logger.warning(
                "Park %s repair plan: decision model down, using the optimum: %s", park_id, exc
            )
            span.update(output=record, level="ERROR", status_message=str(exc))
            return PlanDecision(optimum, record, True)

        pick = _argmax(probabilities)
        pick_plan = by_name[pick]
        optimum_name = next(name for name, plan in by_name.items() if plan == optimum)
        record.update(
            probabilities=_rounded(probabilities),
            model_pick=pick,
            latency_ms=round(1000 * (time.perf_counter() - started)),
            pick_saved=plan_saved(pick_plan),
            optimum_saved=plan_saved(optimum),
            pick_output_lost=round(plan_output_lost(pick_plan, weights, wind), 1),
            optimum_output_lost=round(plan_output_lost(optimum, weights, wind), 1),
        )

        chosen, chosen_name, source = optimum, optimum_name, "rule"
        if mode == _ACTIVE_MODE:
            if plan_saved(pick_plan) < plan_saved(optimum):
                record["reason"] = "rejected"
                source = "rule_fallback"
                logger.warning(
                    "Park %s repair plan: model picked %s saving %d turbines, the optimum saves %d; "
                    "using the optimum",
                    park_id,
                    pick,
                    plan_saved(pick_plan),
                    plan_saved(optimum),
                )
            else:
                chosen, chosen_name, source = pick_plan, pick, "model"
        record.update(chosen=chosen_name, source=source)
        logger.info(
            "Park %s repair plan [%s]: model_pick=%s optimum=%s chosen=%s source=%s p=%s latency_ms=%s",
            park_id,
            mode,
            pick,
            optimum_name,
            chosen_name,
            source,
            record["probabilities"],
            record["latency_ms"],
        )
        span.update(output=record, **_usage(client))
        return PlanDecision(chosen, record, False)


def choose_channel(
    park_id: str,
    item: Mapping[str, Any],
    client: DecisionClient | None,
    mode: str,
    model_down: bool = False,
) -> ChannelDecision:
    """
    Decide how to alert the crew about one turbine.

    A CRITICAL turbine always gets the call and the email. In `activ` mode the model is not asked
    about it; in `umbra` mode it is, only so the log shows when it disagrees.

    :param park_id: The park the turbine belongs to.
    :param item: The turbine's triage item.
    :param client: The decision model client, or None when the model is off.
    :param mode: `"activ"` lets the model decide; anything else only records its pick.
    :param model_down: True when the model already failed earlier in this run.

    :returns decision: The channel to use, the record of how it was chosen, and whether the model
        failed.
    """
    turbine_id = int(item["turbine_id"])
    status = str(item.get("health_status", "NORMAL"))
    rule = classify_alert_channel(
        health_status=status,
        days_to_failure=lead_time_days(item),
        fault_probability=float(item.get("fault_probability") or 0.0),
    )
    critical = status.upper() == "CRITICAL"
    used = AlertChannel.VOICE_CALL if critical else rule
    record: dict[str, Any] = {
        "park": park_id,
        "turbine_id": turbine_id,
        "mode": mode,
        "rule": rule.value,
        "model": None,
        "probabilities": None,
        "used": used.value,
        "source": "hard_rule" if critical else "rule",
        "reason": None,
        "latency_ms": None,
    }

    if client is None:
        record["reason"] = "disabled"
    elif model_down:
        record["reason"] = "model_down"
    elif critical and mode == _ACTIVE_MODE:
        record["reason"] = "hard_rule"
    if client is None or record["reason"] is not None:
        level = logging.DEBUG if record["reason"] == "disabled" else logging.INFO
        logger.log(
            level,
            "Turbine %s alert: %s by %s, model not asked (%s)",
            turbine_id,
            used.value,
            record["source"],
            record["reason"],
        )
        return ChannelDecision(used, record, False)

    request = build_channel_request(park_id, item)
    with tracing.model_call(
        "jev.alert_channel",
        {"mode": mode, "state": request.state, "options": request.options},
        model=_MODEL_NAME,
    ) as span:
        started = time.perf_counter()
        try:
            probabilities = client.choice(request.state, request.instructions, request.options)
        except DecisionModelError as exc:
            record.update(
                reason="error",
                source=(
                    "hard_rule" if critical else "rule_fallback" if mode == _ACTIVE_MODE else "rule"
                ),
                latency_ms=round(1000 * (time.perf_counter() - started)),
            )
            logger.warning(
                "Turbine %s alert: decision model down, using %s by rule: %s",
                turbine_id,
                used.value,
                exc,
            )
            span.update(output=record, level="ERROR", status_message=str(exc))
            return ChannelDecision(used, record, True)

        model = AlertChannel(_argmax(probabilities))
        record.update(
            model=model.value,
            probabilities=_rounded(probabilities),
            latency_ms=round(1000 * (time.perf_counter() - started)),
        )
        if mode == _ACTIVE_MODE:
            used = model
            record.update(used=model.value, source="model")
        elif critical and model != AlertChannel.VOICE_CALL:
            logger.warning(
                "Turbine %s alert: hard rule overrides the model (CRITICAL gets %s, model said %s)",
                turbine_id,
                used.value,
                model.value,
            )
        logger.info(
            "Turbine %s alert [%s]: rule=%s model=%s used=%s source=%s p=%s latency_ms=%s",
            turbine_id,
            mode,
            rule.value,
            model.value,
            used.value,
            record["source"],
            record["probabilities"],
            record["latency_ms"],
        )
        span.update(output=record, **_usage(client))
        return ChannelDecision(used, record, False)


__all__ = ["ChannelDecision", "PlanDecision", "choose_channel", "choose_plan"]
