"""
# LangGraph state graph for autonomous fleet dispatch and alerting

Defines the state graph workflow, conditional routing for power output evaluations,
repair planning, crew matching, and multi-channel alerting.

The flow: predict, triage, overlap check, the power model only when failures overlap, the exact
repair schedule, the choice of repair plan, crew matching in the order of that plan, alerting.
The local decision model (see `model_decisions`) takes part in two places, the choice of plan and
the choice of alert channel, and only after the code has prepared and checked the options.

The following can be imported from this module:
- `build_dispatch_graph`
- `run_park_dispatch_agent`
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from smarthack import config
from smarthack.clients.crew_client import get_default_crew_client
from smarthack.clients.decision_client import get_default_decision_client
from smarthack.constants import CONFLICT_WINDOW_DAYS, WIND_FORECAST_DAYS
from smarthack.schemas.dispatch import AlertChannel, CrewStatus, DispatchDecision
from smarthack.services.agent import tracing
from smarthack.services.agent.failure_overlap import (
    item_failure_day,
    lead_time_days,
    overlapping_failures,
)
from smarthack.services.agent.model_decisions import choose_channel, choose_plan
from smarthack.services.agent.prompts import generate_llm_alert_payload
from smarthack.services.agent.repair_plans import (
    build_requests,
    plan_from_slots,
    plan_order,
    schedule_entries,
)
from smarthack.services.agent.repair_scheduler import schedule_repairs
from smarthack.services.agent.state import DispatchAgentState
from smarthack.services.agent.tools import (
    _use_database,
    dispatch_voice_alert,
    dispatch_warning_email,
    get_available_crews_tool,
    get_daily_wind_forecast,
    get_turbine_location,
    get_turbines_needing_attention,
    predict_wind_power_mwh,
)
from smarthack.utils.dates import today_in_tz

logger = logging.getLogger(__name__)


def node_predict_maintenance(state: DispatchAgentState) -> dict[str, Any]:
    """
    Execute predictive maintenance inference cycle across fleet telemetry before triage.

    Runs the fleet-wide maintenance model cycle (identical to the recurring background job),
    persisting 7-day failure predictions to Supabase before candidate triage.

    :param state: Current agent state.

    :returns update: Updated dictionary with latest telemetry state.
    """
    if _use_database() and not state.get("triage_items"):
        try:
            import asyncio
            import concurrent.futures

            from smarthack.services.maintenance_service import execute_fleet_maintenance_cycle

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    summary = pool.submit(asyncio.run, execute_fleet_maintenance_cycle()).result()
            else:
                summary = asyncio.run(execute_fleet_maintenance_cycle())

            logger.info(
                "Step 1: Fleet maintenance prediction cycle completed (written=%d, by_status=%s)",
                summary.written,
                summary.by_status,
            )
        except Exception as exc:
            logger.warning(
                "Step 1 predictive maintenance cycle encountered non-fatal error: %s", exc
            )

    return {}


def node_triage_park(state: DispatchAgentState) -> dict[str, Any]:
    """
    Filter and identify all turbines in the wind park that require physical repair.

    :param state: Current agent state containing park_id and optional triage items.

    :returns update: Updated dictionary containing failing_turbines.
    """
    park_id = state.get("park_id", "wind_farm_a")
    triage_items = state.get("triage_items", [])
    if not triage_items:
        triage_items = get_turbines_needing_attention(park_id=park_id)
    # The agent works one park at a time: turbines of another park are never compared with these
    # and their crews are never alerted for them, even if a caller passes mixed items.
    triage_items = [t for t in triage_items if str(t.get("park_id", park_id)) == str(park_id)]

    failing = [t for t in triage_items if t.get("needs_repair", False)]
    logger.info("Park %s: %d / %d turbines need repair.", park_id, len(failing), len(triage_items))
    return {"triage_items": triage_items, "failing_turbines": failing}


def node_check_failure_overlap(state: DispatchAgentState) -> dict[str, Any]:
    """
    Load the park's crews and detect turbines predicted to fail in the same interval.

    Two or more turbines of the park whose failure days are at most `CONFLICT_WINDOW_DAYS`
    apart make a conflict: one repair has to come first, so their output must be compared.

    :param state: Current agent state.

    :returns update: Updated dictionary containing available_crews and has_conflict flag.
    """
    park_id = state.get("park_id", "wind_farm_a")
    failing = state.get("failing_turbines", [])
    crews = get_available_crews_tool(park_id=park_id)
    # The crews are about to enter the state, and so every trace: tell the tracing what to hide.
    tracing.register_sensitive(
        value
        for crew in crews
        for value in (crew.get("crew_name"), crew.get("contact_phone"), crew.get("contact_email"))
    )

    # A turbine ML1 expects to last the week (lead time of 8 days or more, or none) has no failure
    # day: it cannot overlap with another, and is not given a made-up day to overlap on.
    failure_days = {
        int(t["turbine_id"]): day for t in failing if (day := item_failure_day(t)) is not None
    }
    overlapping = overlapping_failures(failure_days, CONFLICT_WINDOW_DAYS)
    has_conflict = bool(overlapping)

    logger.info(
        "Park %s: %d failing turbines, %d available crews, overlapping failures=%s",
        park_id,
        len(failing),
        len(crews),
        sorted(overlapping),
    )
    return {"available_crews": crews, "has_conflict": has_conflict}


def route_after_overlap_check(state: DispatchAgentState) -> str:
    """
    Conditional routing edge deciding whether the Wind Power Model must be invoked.

    Only invoked when a choice between turbines failing in the same interval must be made.

    :param state: Current agent state.

    :returns next_node: 'power_prioritization' if conflict, otherwise 'schedule_repairs'.
    """
    if state.get("has_conflict", False):
        logger.info("Failures overlap! Routing to Power Model prioritization.")
        return "power_prioritization"
    logger.info("No overlapping failures. Skipping Power Model evaluation.")
    return "schedule_repairs"


def node_power_prioritization(state: DispatchAgentState) -> dict[str, Any]:
    """
    Invoke the SCADA Wind Power Model to calculate 7-day projected MWh for competing turbines.

    :param state: Current agent state.

    :returns update: State updates containing power_evaluations and annotated turbines.
    """
    failing = state.get("failing_turbines", [])
    power_map: dict[int, float] = {}
    updated_failing: list[dict[str, Any]] = []

    for t_item in failing:
        t_id = int(t_item["turbine_id"])
        loc = get_turbine_location(t_id)
        lat, lon, cap = loc["latitude"], loc["longitude"], loc["capacity_kw"]

        mwh = predict_wind_power_mwh(latitude=lat, longitude=lon, forecast_days=7, capacity_kw=cap)
        power_map[t_id] = mwh

        t_copy = dict(t_item)
        t_copy["projected_mwh_7d"] = mwh
        t_copy["power_evaluated"] = True
        updated_failing.append(t_copy)

    logger.info("Power Model evaluated %d competing turbines: %s", len(power_map), power_map)
    return {
        "power_evaluations": power_map,
        "power_model_invoked": True,
        "failing_turbines": updated_failing,
    }


def node_schedule_repairs(state: DispatchAgentState) -> dict[str, Any]:
    """
    Pick one repair day per failing turbine: single crew, calmest wind, before the failure day.

    This is the exact optimum. The next node may replace it with another plan.

    :param state: Current agent state with the failing turbines, `projected_mwh_7d` set when the
        power model ran.

    :returns update: State update with `repair_schedule` keyed by turbine id, each value holding
        `day` (offset from today), `date` (ISO) and `wind_speed`; `day` and `date` are None
        when no day was left before the predicted failure. `daily_wind` is the forecast used.
    """
    park_id = state.get("park_id", "wind_farm_a")
    failing = state.get("failing_turbines", [])
    if not failing:
        return {"repair_schedule": {}, "daily_wind": []}

    daily_wind = get_daily_wind_forecast(park_id, WIND_FORECAST_DAYS)
    slots = schedule_repairs(build_requests(failing), daily_wind)
    today = today_in_tz(config.timezone())
    schedule = schedule_entries(plan_from_slots(slots), daily_wind, today)
    logger.info("Park %s repair schedule: %s", park_id, schedule)
    return {"repair_schedule": schedule, "daily_wind": daily_wind}


def node_choose_repair_plan(state: DispatchAgentState) -> dict[str, Any]:
    """
    Choose the repair plan the crew follows, among the optimum and a few alternatives.

    The code builds the candidate plans and the local decision model picks one. In `umbra` mode the
    optimum is always kept and the pick is only recorded; in `activ` mode the pick is followed
    unless it saves fewer turbines than the optimum. Without the model, the optimum stands.

    :param state: Current agent state with the failing turbines and the forecast.

    :returns update: `repair_schedule` of the chosen plan and `repair_plan_choice`, the record of
        how it was chosen; `decision_model_down` when the model failed.
    """
    park_id = state.get("park_id", "wind_farm_a")
    failing = state.get("failing_turbines", [])
    if not failing:
        return {}

    daily_wind = state.get("daily_wind", [])
    decision = choose_plan(
        park_id=park_id,
        turbines=failing,
        daily_wind=daily_wind,
        client=get_default_decision_client(),
        mode=config.decision_model_mode(),
        model_down=state.get("decision_model_down", False),
    )
    today = today_in_tz(config.timezone())
    update: dict[str, Any] = {
        "repair_schedule": schedule_entries(decision.chosen, daily_wind, today),
        "repair_plan_choice": decision.record,
    }
    if decision.model_down:
        update["decision_model_down"] = True
    return update


def node_rank_and_match_crews(state: DispatchAgentState) -> dict[str, Any]:
    """
    Order the failing turbines as the chosen plan repairs them, then allocate available crews.

    The order comes from the plan: earliest repair day first, turbines left without a day last
    (higher projected output first). Crews are handed out in that order.

    :param state: Current agent state with the chosen `repair_schedule`.

    :returns update: State updates containing prioritized_turbines and crew_assignments.
    """
    failing = list(state.get("failing_turbines", []))
    available_crews = list(state.get("available_crews", []))
    schedule = state.get("repair_schedule", {})

    plan = {
        int(t["turbine_id"]): schedule.get(int(t["turbine_id"]), {}).get("day") for t in failing
    }
    weights = {int(t["turbine_id"]): float(t.get("projected_mwh_7d") or 0.0) for t in failing}
    rank = {turbine_id: i for i, turbine_id in enumerate(plan_order(plan, weights))}
    sorted_turbines = sorted(failing, key=lambda item: rank[int(item["turbine_id"])])

    crew_assignments: dict[int, str] = {}
    crew_pool = list(available_crews)

    for item in sorted_turbines:
        t_id = int(item["turbine_id"])
        if crew_pool:
            matched_crew = crew_pool.pop(0)
            crew_assignments[t_id] = str(matched_crew["crew_id"])
        else:
            # Deferred due to crew shortage
            crew_assignments[t_id] = ""

    return {
        "prioritized_turbines": sorted_turbines,
        "crew_assignments": crew_assignments,
    }


def node_decide_and_dispatch_alerts(state: DispatchAgentState) -> dict[str, Any]:
    """
    Determine the alerting channel and execute dispatches.

    The channel is chosen by `choose_channel`: the rule, with the local decision model's pick
    recorded beside it in `umbra` mode, or the model's pick in `activ` mode. A CRITICAL turbine
    always gets the call. The call comes with the email: a call alone leaves the crew nothing
    written to act from.

    :param state: Current agent state.

    :returns update: Final state containing alert_decisions, notifications_dispatched and
        channel_decisions (how each channel was chosen); `decision_model_down` when the model failed.
    """
    park_id = state.get("park_id", "wind_farm_a")
    prioritized = state.get("prioritized_turbines", [])
    crew_assignments = state.get("crew_assignments", {})
    available_crews = state.get("available_crews", [])
    crew_map = {c["crew_id"]: c for c in available_crews}
    crew_client = get_default_crew_client()
    decision_client = get_default_decision_client()
    mode = config.decision_model_mode()
    model_down = state.get("decision_model_down", False)

    decisions: list[dict[str, Any]] = []
    dispatched_notifications: list[dict[str, Any]] = []
    channel_records: list[dict[str, Any]] = []

    for rank_idx, item in enumerate(prioritized, start=1):
        t_id = int(item["turbine_id"])
        status = str(item.get("health_status", "NORMAL"))
        days_to_fail = lead_time_days(item)
        fault_prob = float(item.get("fault_probability") or 0.0)
        suspected = str(item.get("suspected_failure", "Unknown"))
        mwh = item.get("projected_mwh_7d")

        # Core Agent Mandate: Decision of Alerting
        channel_decision = choose_channel(
            park_id=park_id,
            item=item,
            client=decision_client,
            mode=mode,
            model_down=model_down,
        )
        channel = channel_decision.channel
        model_down = model_down or channel_decision.model_down
        channel_records.append(channel_decision.record)

        assigned_crew_id = crew_assignments.get(t_id) or None
        assigned_crew_data = crew_map.get(assigned_crew_id) if assigned_crew_id else None
        assigned_crew_name = assigned_crew_data["crew_name"] if assigned_crew_data else None

        # Fallback recipient: park lead crew if this specific turbine had to be deferred
        fallback_crew = available_crews[0] if available_crews else None
        recipient_crew = assigned_crew_data or fallback_crew
        target_name = recipient_crew["crew_name"] if recipient_crew else f"Park Lead ({park_id})"
        target_phone = (
            recipient_crew.get("contact_phone", "+1-555-0100") if recipient_crew else "+1-555-0100"
        )
        target_email = (
            recipient_crew.get("contact_email", f"lead@{park_id}.com")
            if recipient_crew
            else f"lead@{park_id}.com"
        )

        llm_payload = generate_llm_alert_payload(
            turbine_id=t_id,
            park_id=park_id,
            channel=channel,
            health_status=status,
            days_to_failure=days_to_fail,
            fault_probability=fault_prob,
            suspected_failure=suspected,
            recommended_action=str(item.get("recommended_action", "Inspect component.")),
            mwh=mwh,
            assigned_crew=assigned_crew_name,
        )

        reason = llm_payload["decision_reason"]
        repair = state.get("repair_schedule", {}).get(t_id)
        repair_date = repair["date"] if repair else None
        repair_line = ""
        if repair is not None and repair_date:
            wind_note = (
                " (no wind forecast available)"
                if repair["wind_speed"] is None
                else f" (forecast wind {repair['wind_speed']:.1f} m/s)"
            )
            repair_line = f"Repair planned for {repair_date}{wind_note}."
        elif repair is not None:
            repair_line = "No repair day is left before the predicted failure."
        if repair_line:
            reason += f" {repair_line}"
        notification_sent = False
        message_body = ""

        if channel == AlertChannel.VOICE_CALL:
            message_body = f"{llm_payload['speech_text']} {repair_line}".strip()
            resp = dispatch_voice_alert(
                phone_number=target_phone,
                crew_name=target_name,
                turbine_id=t_id,
                park_id=park_id,
                message=message_body,
                lead_time_hours=days_to_fail * 24.0,
                fault_probability=fault_prob,
            )
            dispatched_notifications.append(resp)
            notification_sent = True

        if channel in (AlertChannel.VOICE_CALL, AlertChannel.EMAIL):
            email_body = f"{llm_payload['email_body']}\n{repair_line}".strip()
            message_body = message_body or email_body
            resp = dispatch_warning_email(
                recipient_email=target_email,
                crew_name=target_name,
                turbine_id=t_id,
                park_id=park_id,
                subject=llm_payload["email_subject"],
                body=email_body,
                diagnostics={
                    "subsystem_risks": item.get("subsystem_risks", {}),
                    "daily_forecast": item.get("daily_forecast", []),
                    "projected_mwh_7d": mwh,
                    "repair_date": repair_date,
                },
                real_alert=(
                    {
                        "health_status": status,
                        "lead_time_hours": days_to_fail * 24.0,
                        "fault_probability": fault_prob,
                    }
                    if channel == AlertChannel.EMAIL
                    else None
                ),
            )
            dispatched_notifications.append(resp)
            notification_sent = True

        # If assigned, update crew status in client
        if assigned_crew_id and not _use_database():
            crew_client.update_crew_status(assigned_crew_id, CrewStatus.DISPATCHED)

        decision = DispatchDecision(
            turbine_id=t_id,
            park_id=park_id,
            health_status=status,
            priority_rank=rank_idx,
            alert_channel=channel,
            assigned_crew_id=assigned_crew_id,
            assigned_crew_name=assigned_crew_name,
            repair_date=repair_date,
            notification_sent=notification_sent,
            notification_message=message_body,
            decision_reason=reason,
        )
        decisions.append(decision.model_dump())

    audit_summary = (
        f"Park {park_id} Sweep: Evaluated {len(prioritized)} failing turbines. "
        f"Alerts dispatched: {len(dispatched_notifications)}. "
        f"Power model invoked: {state.get('power_model_invoked', False)}."
    )

    update: dict[str, Any] = {
        "alert_decisions": decisions,
        "notifications_dispatched": dispatched_notifications,
        "channel_decisions": channel_records,
        "audit_summary": audit_summary,
    }
    if model_down:
        update["decision_model_down"] = True
    return update


def build_dispatch_graph() -> Any:
    """
    Construct and compile the LangGraph StateGraph workflow for park maintenance dispatch.

    :returns app: Compiled LangGraph application.
    """
    builder: StateGraph = StateGraph(DispatchAgentState)

    builder.add_node("predict_maintenance", node_predict_maintenance)
    builder.add_node("triage_park", node_triage_park)
    builder.add_node("check_failure_overlap", node_check_failure_overlap)
    builder.add_node("power_prioritization", node_power_prioritization)
    builder.add_node("schedule_repairs", node_schedule_repairs)
    builder.add_node("choose_repair_plan", node_choose_repair_plan)
    builder.add_node("rank_and_match_crews", node_rank_and_match_crews)
    builder.add_node("decide_and_dispatch_alerts", node_decide_and_dispatch_alerts)

    builder.add_edge(START, "predict_maintenance")
    builder.add_edge("predict_maintenance", "triage_park")
    builder.add_edge("triage_park", "check_failure_overlap")
    builder.add_conditional_edges(
        "check_failure_overlap",
        route_after_overlap_check,
        {
            "power_prioritization": "power_prioritization",
            "schedule_repairs": "schedule_repairs",
        },
    )
    builder.add_edge("power_prioritization", "schedule_repairs")
    builder.add_edge("schedule_repairs", "choose_repair_plan")
    builder.add_edge("choose_repair_plan", "rank_and_match_crews")
    builder.add_edge("rank_and_match_crews", "decide_and_dispatch_alerts")
    builder.add_edge("decide_and_dispatch_alerts", END)

    return builder.compile()


def run_park_dispatch_agent(
    park_id: str,
    triage_items: list[dict[str, Any]] | None = None,
) -> DispatchAgentState:
    """
    Execute the compiled LangGraph agent workflow for a designated wind park.

    :param park_id: The wind park identifier.
    :param triage_items: Optional pre-computed triage dictionaries.

    :returns final_state: Resulting state dictionary following graph termination.
    """
    graph = build_dispatch_graph()
    initial_state: DispatchAgentState = {
        "park_id": park_id,
        "triage_items": triage_items or [],
        "failing_turbines": [],
        "available_crews": [],
        "has_conflict": False,
        "power_evaluations": {},
        "power_model_invoked": False,
        "prioritized_turbines": [],
        "crew_assignments": {},
        "daily_wind": [],
        "repair_schedule": {},
        "repair_plan_choice": {},
        "channel_decisions": [],
        "decision_model_down": False,
        "alert_decisions": [],
        "notifications_dispatched": [],
        "audit_summary": "",
    }
    # The agent reads the triage itself when none is given: no count to show before it has run.
    run_input: dict[str, Any] = {"park_id": park_id}
    if triage_items is not None:
        run_input["triage_items"] = len(triage_items)
    try:
        with tracing.agent_run(park_id, run_input) as run:
            result = graph.invoke(initial_state, config=run.config)
            run.update(
                output={
                    "audit_summary": result.get("audit_summary", ""),
                    "decisions": len(result.get("alert_decisions", [])),
                    "decision_model_down": result.get("decision_model_down", False),
                }
            )
    finally:
        tracing.flush()
    return result


__all__ = ["build_dispatch_graph", "run_park_dispatch_agent"]
