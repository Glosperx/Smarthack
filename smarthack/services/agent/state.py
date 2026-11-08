"""
# Agent state definition

TypedDict state schema for the LangGraph autonomous dispatch and alerting agent.

The following can be imported from this module:
- `DispatchAgentState`
"""

from typing import Any, TypedDict


class DispatchAgentState(TypedDict, total=False):
    """
    State dictionary flowing through the LangGraph dispatch workflow nodes.

    Captures the park-level lifecycle from fleet scan to crew assignment and dual alerting.

    `daily_wind` is the forecast the schedule was built on. `repair_schedule` is the plan the crew
    follows. `repair_plan_choice` and `channel_decisions` record how the plan and each alert
    channel were chosen (options, probabilities, who decided). `decision_model_down` is set when
    the local decision model fails, so the rest of the run does not wait on it again.
    """

    park_id: str
    triage_items: list[dict[str, Any]]
    failing_turbines: list[dict[str, Any]]
    available_crews: list[dict[str, Any]]
    has_conflict: bool
    power_evaluations: dict[int, float]
    power_model_invoked: bool
    prioritized_turbines: list[dict[str, Any]]
    crew_assignments: dict[int, str]
    daily_wind: list[float | None]
    repair_schedule: dict[int, dict[str, Any]]
    repair_plan_choice: dict[str, Any]
    channel_decisions: list[dict[str, Any]]
    decision_model_down: bool
    alert_decisions: list[dict[str, Any]]
    notifications_dispatched: list[dict[str, Any]]
    audit_summary: str


__all__ = ["DispatchAgentState"]
