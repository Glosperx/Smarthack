"""
# LangGraph state graph for autonomous fleet dispatch and alerting

Defines the state graph workflow, conditional routing for power output evaluations,
crew matching, and multi-channel alerting.

The following can be imported from this module:
- `build_dispatch_graph`
- `run_park_dispatch_agent`
"""

from datetime import timedelta
import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from smarthack import config
from smarthack.clients.crew_client import get_default_crew_client
from smarthack.constants import CONFLICT_WINDOW_DAYS, WIND_FORECAST_DAYS
from smarthack.schemas.dispatch import AlertChannel, CrewStatus, DispatchDecision
from smarthack.services.agent.failure_overlap import failure_day, overlapping_failures
from smarthack.services.agent.prompts import (
    classify_alert_channel,
    generate_llm_alert_payload,
)
from smarthack.services.agent.repair_scheduler import RepairRequest, schedule_repairs
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

    failure_days = {
        int(t["turbine_id"]): failure_day(float(t.get("days_to_failure", WIND_FORECAST_DAYS)))
        for t in failing
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

    :returns next_node: 'power_prioritization' if conflict, otherwise 'rank_and_match_crews'.
    """
    if state.get("has_conflict", False):
        logger.info("Failures overlap! Routing to Power Model prioritization.")
        return "power_prioritization"
    logger.info("No overlapping failures. Skipping Power Model evaluation.")
    return "rank_and_match_crews"


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


def node_rank_and_match_crews(state: DispatchAgentState) -> dict[str, Any]:
    """
    Rank failing turbines by criticality, power output, and lead time, then allocate available crews.

    :param state: Current agent state.

    :returns update: State updates containing prioritized_turbines and crew_assignments.
    """
    failing = list(state.get("failing_turbines", []))
    available_crews = list(state.get("available_crews", []))

    def sort_key(item: dict[str, Any]) -> tuple[int, float, float]:
        """Compute compound sorting tuple for dispatch ranking."""
        is_critical = 1 if str(item.get("health_status", "")).upper() == "CRITICAL" else 0
        power_mwh = float(item.get("projected_mwh_7d") or 0.0)
        days_to_fail = float(item.get("days_to_failure", 7.0))
        # Criticality first (descending), power generation loss (descending), lead time (ascending)
        return (is_critical, power_mwh, -days_to_fail)

    sorted_turbines = sorted(failing, key=sort_key, reverse=True)

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


def node_schedule_repairs(state: DispatchAgentState) -> dict[str, Any]:
    """
    Pick one repair day per failing turbine: single crew, calmest wind, before the failure day.

    :param state: Current agent state with the prioritized turbines.

    :returns update: State update with `repair_schedule` keyed by turbine id, each value holding
        `day` (offset from today), `date` (ISO) and `wind_speed`; `day` and `date` are None
        when no day was left before the predicted failure.
    """
    park_id = state.get("park_id", "wind_farm_a")
    prioritized = state.get("prioritized_turbines", [])
    if not prioritized:
        return {"repair_schedule": {}}

    requests = [
        RepairRequest(
            turbine_id=int(t["turbine_id"]),
            failure_day=failure_day(float(t.get("days_to_failure", WIND_FORECAST_DAYS))),
            weight=1.0 if t.get("projected_mwh_7d") is None else float(t["projected_mwh_7d"]),
        )
        for t in prioritized
    ]
    if not any(r.weight > 0 for r in requests):
        # No usable output estimate (power model offline, or zero everywhere): weigh all equally
        # so the wind forecast still decides the day instead of every day looking the same.
        requests = [RepairRequest(r.turbine_id, r.failure_day) for r in requests]
    slots = schedule_repairs(requests, get_daily_wind_forecast(park_id, WIND_FORECAST_DAYS))

    today = today_in_tz(config.timezone())
    schedule: dict[int, dict[str, Any]] = {
        turbine_id: {
            "day": slot.day,
            "date": None if slot.day is None else (today + timedelta(days=slot.day)).isoformat(),
            "wind_speed": slot.wind_speed,
        }
        for turbine_id, slot in slots.items()
    }
    logger.info("Park %s repair schedule: %s", park_id, schedule)
    return {"repair_schedule": schedule}


def node_decide_and_dispatch_alerts(state: DispatchAgentState) -> dict[str, Any]:
    """
    Determine the alerting channel (Voice Call TTS vs Email ticket) and execute dispatches.

    :param state: Current agent state.

    :returns update: Final state containing alert_decisions and notifications_dispatched.
    """
    park_id = state.get("park_id", "wind_farm_a")
    prioritized = state.get("prioritized_turbines", [])
    crew_assignments = state.get("crew_assignments", {})
    available_crews = state.get("available_crews", [])
    crew_map = {c["crew_id"]: c for c in available_crews}
    crew_client = get_default_crew_client()

    decisions: list[dict[str, Any]] = []
    dispatched_notifications: list[dict[str, Any]] = []

    for rank_idx, item in enumerate(prioritized, start=1):
        t_id = int(item["turbine_id"])
        status = str(item.get("health_status", "NORMAL"))
        days_to_fail = float(item.get("days_to_failure", 7.0))
        fault_prob = float(item.get("fault_probability", 0.0))
        suspected = str(item.get("suspected_failure", "Unknown"))
        mwh = item.get("projected_mwh_7d")

        # Core Agent Mandate: Decision of Alerting
        channel = classify_alert_channel(
            health_status=status,
            days_to_failure=days_to_fail,
            fault_probability=fault_prob,
        )

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

        elif channel == AlertChannel.EMAIL:
            subject = llm_payload["email_subject"]
            message_body = f"{llm_payload['email_body']}\n{repair_line}".strip()
            resp = dispatch_warning_email(
                recipient_email=target_email,
                crew_name=target_name,
                turbine_id=t_id,
                park_id=park_id,
                subject=subject,
                body=message_body,
                diagnostics={
                    "subsystem_risks": item.get("subsystem_risks", {}),
                    "daily_forecast": item.get("daily_forecast", []),
                    "projected_mwh_7d": mwh,
                    "repair_date": repair_date,
                },
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

    return {
        "alert_decisions": decisions,
        "notifications_dispatched": dispatched_notifications,
        "audit_summary": audit_summary,
    }


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
    builder.add_node("rank_and_match_crews", node_rank_and_match_crews)
    builder.add_node("schedule_repairs", node_schedule_repairs)
    builder.add_node("decide_and_dispatch_alerts", node_decide_and_dispatch_alerts)

    builder.add_edge(START, "predict_maintenance")
    builder.add_edge("predict_maintenance", "triage_park")
    builder.add_edge("triage_park", "check_failure_overlap")
    builder.add_conditional_edges(
        "check_failure_overlap",
        route_after_overlap_check,
        {
            "power_prioritization": "power_prioritization",
            "rank_and_match_crews": "rank_and_match_crews",
        },
    )
    builder.add_edge("power_prioritization", "rank_and_match_crews")
    builder.add_edge("rank_and_match_crews", "schedule_repairs")
    builder.add_edge("schedule_repairs", "decide_and_dispatch_alerts")
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
        "repair_schedule": {},
        "alert_decisions": [],
        "notifications_dispatched": [],
        "audit_summary": "",
    }
    result = graph.invoke(initial_state)
    return result


__all__ = ["build_dispatch_graph", "run_park_dispatch_agent"]
