"""
# Dispatch agent prompts and decision reasoning rules

System instructions and heuristic decision rules for the alerting agent.

The following can be imported from this module:
- `SYSTEM_DISPATCH_PROMPT`
- `build_alert_explanation`
- `classify_alert_channel`
"""

from smarthack.schemas.dispatch import AlertChannel

SYSTEM_DISPATCH_PROMPT = """
You are the Autonomous Fleet Dispatch & Alerting Agent for industrial wind power parks.

Your core mission:
1. Examine predictive maintenance reports for turbines exhibiting impending faults over a 7-day horizon.
2. Resolve maintenance crew shortages by prioritizing higher power-generating assets to minimize electricity curtailment.
3. Make definitive alerting decisions based on physical criticality:
   - CRITICAL (lead time <= 48 hours, fault probability >= 0.70, or runaway thermal/bearing failure):
     Alert the dedicated park crew IMMEDIATELY via an automated text-to-speech (TTS) emergency phone call.
   - WARNING / NON-CRITICAL (lead time 3-7 days, moderate probability, emerging component wear):
     Dispatch a standard maintenance work order ticket via EMAIL.
4. Ensure only maintenance crews assigned to the specific wind park are alerted.
"""


def classify_alert_channel(
    health_status: str,
    days_to_failure: float,
    fault_probability: float,
) -> AlertChannel:
    """
    Classify the required alerting channel based on physical risk urgency.

    :param health_status: Assessed health state (e.g. CRITICAL, WARNING, WATCH, NORMAL).
    :param days_to_failure: Days remaining until functional failure.
    :param fault_probability: 7-day failure likelihood score.

    :returns channel: AlertChannel.VOICE_CALL for urgent emergencies, AlertChannel.EMAIL for warnings.
    """
    status_upper = health_status.upper()
    if status_upper == "CRITICAL" or days_to_failure <= 2.0 or fault_probability >= 0.70:
        return AlertChannel.VOICE_CALL
    if status_upper in ("WARNING", "WATCH") or fault_probability >= 0.30:
        return AlertChannel.EMAIL
    return AlertChannel.NONE


def build_alert_explanation(
    turbine_id: int,
    park_id: str,
    channel: AlertChannel,
    health_status: str,
    days_to_failure: float,
    suspected_failure: str,
    mwh: float | None = None,
    assigned_crew: str | None = None,
) -> str:
    """
    Generate an explanatory audit rationale for the dispatch decision.

    :param turbine_id: Asset identifier.
    :param park_id: Wind park identifier.
    :param channel: Selected notification channel.
    :param health_status: Assessed physical status.
    :param days_to_failure: Days to failure lead time.
    :param suspected_failure: Suspected component fault.
    :param mwh: Projected MWh electricity generation if calculated.
    :param assigned_crew: Name of assigned crew if allocated.

    :returns explanation: Comprehensive human-readable audit text.
    """
    mwh_note = f", projected {mwh:.1f} MWh output loss" if mwh is not None else ""
    crew_note = f"Assigned to {assigned_crew}." if assigned_crew else "Deferred to next shift."

    if channel == AlertChannel.VOICE_CALL:
        return (
            f"CRITICAL DISPATCH: Turbine {turbine_id} in {park_id} has imminent failure "
            f"({suspected_failure}) in {days_to_failure:.1f} days{mwh_note}. "
            f"Voice call triggered to ensure immediate physical intervention. {crew_note}"
        )
    if channel == AlertChannel.EMAIL:
        return (
            f"PREVENTIVE TICKET: Turbine {turbine_id} in {park_id} exhibits {health_status} "
            f"condition ({suspected_failure}) with {days_to_failure:.1f} days lead time{mwh_note}. "
            f"Email work order ticket dispatched for routine scheduling. {crew_note}"
        )
    return f"Turbine {turbine_id} in {park_id} is in normal operational condition."


__all__ = ["SYSTEM_DISPATCH_PROMPT", "build_alert_explanation", "classify_alert_channel"]
