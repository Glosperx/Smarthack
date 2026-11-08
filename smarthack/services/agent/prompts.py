"""
# Dispatch agent prompts and decision reasoning rules

System instructions, LLM synthesis helpers, and heuristic decision rules for the alerting agent.

The following can be imported from this module:
- `SYSTEM_DISPATCH_PROMPT`
- `build_alert_explanation`
- `classify_alert_channel`
- `generate_llm_alert_payload`
"""

import json
import logging
import re

from smarthack import config
from smarthack.constants import (
    CHANNEL_CALL_DAYS,
    CHANNEL_CALL_PROBABILITY,
    CHANNEL_EMAIL_PROBABILITY,
)
from smarthack.schemas.dispatch import AlertChannel

logger = logging.getLogger(__name__)

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
    if (
        status_upper == "CRITICAL"
        or days_to_failure <= CHANNEL_CALL_DAYS
        or fault_probability >= CHANNEL_CALL_PROBABILITY
    ):
        return AlertChannel.VOICE_CALL
    if status_upper in ("WARNING", "WATCH") or fault_probability >= CHANNEL_EMAIL_PROBABILITY:
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


def generate_llm_alert_payload(
    turbine_id: int,
    park_id: str,
    channel: AlertChannel,
    health_status: str,
    days_to_failure: float,
    fault_probability: float,
    suspected_failure: str,
    recommended_action: str,
    mwh: float | None = None,
    assigned_crew: str | None = None,
) -> dict[str, str]:
    """
    Generate dynamic reasoning and alert copy using the Google Gemini model.

    Falls back to deterministic templating if GEMINI_API_KEY is not configured.

    :param turbine_id: Asset identifier.
    :param park_id: Wind park identifier.
    :param channel: AlertChannel.VOICE_CALL or EMAIL.
    :param health_status: Assessed health status.
    :param days_to_failure: Days remaining to breakdown.
    :param fault_probability: 7-day failure risk score.
    :param suspected_failure: Failing subsystem name.
    :param recommended_action: Maintenance instruction protocol.
    :param mwh: Forecasted MWh generation if evaluated.
    :param assigned_crew: Name of assigned maintenance crew lead.

    :returns payload: Dict with keys 'speech_text', 'email_subject', 'email_body', 'decision_reason'.
    """
    default_reason = build_alert_explanation(
        turbine_id=turbine_id,
        park_id=park_id,
        channel=channel,
        health_status=health_status,
        days_to_failure=days_to_failure,
        suspected_failure=suspected_failure,
        mwh=mwh,
        assigned_crew=assigned_crew,
    )

    hours = days_to_failure * 24.0
    default_speech = (
        f"Emergency alert for {assigned_crew or 'maintenance crew'}. "
        f"Turbine {turbine_id} in {park_id} is in CRITICAL condition. "
        f"Imminent {suspected_failure} predicted in {hours:.0f} hours. "
        f"Immediate intervention required: {recommended_action}."
    )

    default_subject = (
        f"[{health_status}] Maintenance Work Ticket - Turbine {turbine_id} ({park_id})"
    )
    default_body = (
        f"Predictive maintenance sweep detected {health_status} condition for Turbine {turbine_id} in {park_id}.\n"
        f"Component: {suspected_failure}\n"
        f"Lead Time: {days_to_failure:.1f} days ({hours:.0f} hours)\n"
        f"Fault Probability: {fault_probability * 100:.1f}%\n"
        f"Action: {recommended_action}\n"
        f"Assigned Crew: {assigned_crew or 'DEFERRED (Next Shift)'}"
    )

    api_key = config.gemini_api_key()
    if not api_key:
        return {
            "speech_text": default_speech,
            "email_subject": default_subject,
            "email_body": default_body,
            "decision_reason": default_reason,
        }

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        prompt = (
            f"You are the Autonomous Wind Turbine Dispatch Agent.\n"
            f"Asset Diagnostics:\n"
            f"- Turbine: {turbine_id}\n"
            f"- Wind Park: {park_id}\n"
            f"- Status: {health_status}\n"
            f"- Component: {suspected_failure}\n"
            f"- Lead Time: {days_to_failure:.1f} days ({hours:.0f} hours)\n"
            f"- Probability: {fault_probability * 100:.1f}%\n"
            f"- Projected MWh at risk: {mwh or 0.0:.1f} MWh\n"
            f"- Assigned Crew: {assigned_crew or 'Deferred to next shift'}\n"
            f"- Channel: {channel.value}\n"
            f"- Recommended Action: {recommended_action}\n\n"
            f"Output a valid JSON object with:\n"
            f'1. "speech_text": Concise, urgent, realistic spoken alert for automated text-to-speech (under 35 words).\n'
            f'2. "email_subject": Professional engineering subject line.\n'
            f'3. "email_body": Clear technical body (2-3 sentences with telemetry details).\n'
            f'4. "decision_reason": 1-2 sentence audit rationale explaining prioritization and alerting channel.\n'
            f"Respond with JSON ONLY."
        )

        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = (resp.text or "").strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return {
                "speech_text": str(data.get("speech_text") or default_speech),
                "email_subject": str(data.get("email_subject") or default_subject),
                "email_body": str(data.get("email_body") or default_body),
                "decision_reason": str(data.get("decision_reason") or default_reason),
            }
    except Exception as exc:
        logger.warning("Gemini dynamic alerting failed; falling back to templates: %s", exc)

    return {
        "speech_text": default_speech,
        "email_subject": default_subject,
        "email_body": default_body,
        "decision_reason": default_reason,
    }


__all__ = [
    "SYSTEM_DISPATCH_PROMPT",
    "build_alert_explanation",
    "classify_alert_channel",
    "generate_llm_alert_payload",
]
