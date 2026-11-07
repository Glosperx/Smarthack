"""
# Unit tests for LangGraph dispatch agent workflow

Validates conditional power model prioritization, crew conflict resolution,
park-scoped crew alerts, and dual-channel (TTS vs Email) alerting.
"""

import pytest

from smarthack.clients.crew_client import get_default_crew_client
from smarthack.clients.email_client import get_default_email_client
from smarthack.clients.voice_client import get_default_voice_client
from smarthack.schemas.dispatch import AlertChannel, CrewStatus
from smarthack.services.agent.graph import run_park_dispatch_agent
from smarthack.services.agent.prompts import (
    classify_alert_channel,
    generate_llm_alert_payload,
)


@pytest.fixture(autouse=True)
def _isolate_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure unit tests run deterministically without external API latency."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_classify_alert_channel() -> None:
    """Verify alert channel classification rules."""
    # Critical by status
    assert (
        classify_alert_channel("CRITICAL", days_to_failure=5.0, fault_probability=0.2)
        == AlertChannel.VOICE_CALL
    )

    # Critical by lead time (<= 2.0 days)
    assert (
        classify_alert_channel("WARNING", days_to_failure=1.5, fault_probability=0.6)
        == AlertChannel.VOICE_CALL
    )

    # Critical by high probability (>= 0.70)
    assert (
        classify_alert_channel("WATCH", days_to_failure=4.0, fault_probability=0.85)
        == AlertChannel.VOICE_CALL
    )

    # Warning by status / lead time
    assert (
        classify_alert_channel("WARNING", days_to_failure=4.0, fault_probability=0.5)
        == AlertChannel.EMAIL
    )

    # Normal / healthy
    assert (
        classify_alert_channel("NORMAL", days_to_failure=7.0, fault_probability=0.05)
        == AlertChannel.NONE
    )


def test_no_conflict_bypasses_power_model() -> None:
    """
    Verify that when available crews >= failing turbines, the power model is bypassed.
    """
    crew_client = get_default_crew_client()
    crew_client.reset_crews()  # wind_farm_a has 2 available crews

    # Single failing turbine in wind_farm_a
    triage_items = [
        {
            "turbine_id": 0,
            "park_id": "wind_farm_a",
            "health_status": "WARNING",
            "fault_probability": 0.65,
            "days_to_failure": 4.0,
            "suspected_failure": "Gearbox Wear",
            "recommended_action": "Schedule oil filter change.",
            "needs_repair": True,
        },
        {
            "turbine_id": 1,
            "park_id": "wind_farm_a",
            "health_status": "NORMAL",
            "fault_probability": 0.05,
            "days_to_failure": 7.0,
            "suspected_failure": "None",
            "recommended_action": "No action needed.",
            "needs_repair": False,
        },
    ]

    result = run_park_dispatch_agent("wind_farm_a", triage_items=triage_items)

    assert result["has_conflict"] is False
    assert result["power_model_invoked"] is False
    assert len(result["alert_decisions"]) == 1

    decision = result["alert_decisions"][0]
    assert decision["turbine_id"] == 0
    assert decision["alert_channel"] == AlertChannel.EMAIL.value
    assert decision["assigned_crew_id"] is not None
    assert decision["notification_sent"] is True


def test_conflict_invokes_power_model_and_prioritizes() -> None:
    """
    Verify that when failing turbines > available crews, the power model is invoked
    and higher-yield assets receive crew priority.
    """
    crew_client = get_default_crew_client()
    crew_client.reset_crews()

    # Artificially limit wind_farm_a to only 1 available crew
    crew_client.update_crew_status("crew_a2", CrewStatus.OFF_SHIFT)

    # 2 failing turbines competing for 1 crew
    triage_items = [
        {
            "turbine_id": 0,
            "park_id": "wind_farm_a",
            "health_status": "WARNING",
            "fault_probability": 0.60,
            "days_to_failure": 4.0,
            "suspected_failure": "Gearbox Wear",
            "recommended_action": "Inspection required.",
            "needs_repair": True,
        },
        {
            "turbine_id": 1,
            "park_id": "wind_farm_a",
            "health_status": "WARNING",
            "fault_probability": 0.60,
            "days_to_failure": 4.0,
            "suspected_failure": "Hydraulic Pressure Drop",
            "recommended_action": "Seal check.",
            "needs_repair": True,
        },
    ]

    result = run_park_dispatch_agent("wind_farm_a", triage_items=triage_items)

    assert result["has_conflict"] is True
    assert result["power_model_invoked"] is True
    assert len(result["power_evaluations"]) == 2
    assert len(result["alert_decisions"]) == 2

    # Verify crew assignment: 1st gets crew, 2nd is deferred
    d1 = result["alert_decisions"][0]
    d2 = result["alert_decisions"][1]

    assert d1["priority_rank"] == 1
    assert d1["assigned_crew_id"] == "crew_a1"

    assert d2["priority_rank"] == 2
    assert d2["assigned_crew_id"] is None
    assert "deferred" in d2["decision_reason"].lower()


def test_overlapping_failures_invoke_power_model_even_with_enough_crews() -> None:
    """Two turbines due the same day make a conflict although two crews are free."""
    get_default_crew_client().reset_crews()
    triage_items = [_failing(0, 4.0), _failing(1, 4.5)]

    result = run_park_dispatch_agent("wind_farm_a", triage_items=triage_items)

    assert len(result["available_crews"]) == 2
    assert result["has_conflict"] is True
    assert result["power_model_invoked"] is True


def test_failures_far_apart_skip_power_model_even_with_one_crew() -> None:
    """Turbines due days apart need no comparison, however few crews there are."""
    crew_client = get_default_crew_client()
    crew_client.reset_crews()
    crew_client.update_crew_status("crew_a2", CrewStatus.OFF_SHIFT)
    triage_items = [_failing(0, 2.0), _failing(1, 6.0)]

    result = run_park_dispatch_agent("wind_farm_a", triage_items=triage_items)

    assert len(result["available_crews"]) == 1
    assert result["has_conflict"] is False
    assert result["power_model_invoked"] is False


def _failing(turbine_id: int, days_to_failure: float) -> dict[str, object]:
    """
    Build a triage item for a turbine that needs repair.

    :param turbine_id: Turbine identifier.
    :param days_to_failure: Predicted days until failure.

    :returns item: Triage dictionary as the maintenance model produces it.
    """
    return {
        "turbine_id": turbine_id,
        "park_id": "wind_farm_a",
        "health_status": "WARNING",
        "fault_probability": 0.6,
        "days_to_failure": days_to_failure,
        "suspected_failure": "Gearbox Wear",
        "recommended_action": "Inspect.",
        "needs_repair": True,
    }


def test_critical_fault_triggers_voice_call() -> None:
    """Verify that a critical turbine triggers a text-to-speech voice alert."""
    voice_client = get_default_voice_client()
    voice_client.clear_history()

    triage_items = [
        {
            "turbine_id": 0,
            "park_id": "wind_farm_a",
            "health_status": "CRITICAL",
            "fault_probability": 0.95,
            "days_to_failure": 0.8,
            "suspected_failure": "Generator Bearing Overheating",
            "recommended_action": "Immediate thermal shutdown.",
            "needs_repair": True,
        }
    ]

    result = run_park_dispatch_agent("wind_farm_a", triage_items=triage_items)

    decision = result["alert_decisions"][0]
    assert decision["alert_channel"] == AlertChannel.VOICE_CALL.value
    assert decision["notification_sent"] is True

    voice_history = voice_client.get_call_history()
    assert len(voice_history) == 1
    assert voice_history[0]["turbine_id"] == 0
    assert "CRITICAL" in voice_history[0]["synthesized_speech"]


def test_park_scoped_crew_isolation() -> None:
    """
    Verify that faults in wind_farm_b ONLY alert wind_farm_b crews, never wind_farm_a.
    """
    crew_client = get_default_crew_client()
    crew_client.reset_crews()
    email_client = get_default_email_client()
    email_client.clear_history()

    triage_items = [
        {
            "turbine_id": 10,
            "park_id": "wind_farm_b",
            "health_status": "WARNING",
            "fault_probability": 0.55,
            "days_to_failure": 3.5,
            "suspected_failure": "Pitch Actuator Wear",
            "recommended_action": "Replace valve seal.",
            "needs_repair": True,
        }
    ]

    result = run_park_dispatch_agent("wind_farm_b", triage_items=triage_items)

    decision = result["alert_decisions"][0]
    # Must be assigned to Gamma Team (park b), NOT Alpha or Beta (park a)
    assert decision["assigned_crew_id"] == "crew_b1"
    assert decision["assigned_crew_name"] == "Gamma Response Team"

    emails = email_client.get_email_history()
    assert len(emails) == 1
    assert emails[0]["park_id"] == "wind_farm_b"
    assert "gamma.crew@windfarmb.com" in emails[0]["recipient_email"]


def test_generate_llm_alert_payload_fallback() -> None:
    """Verify LLM helper fallback when GEMINI_API_KEY is not set."""
    payload = generate_llm_alert_payload(
        turbine_id=0,
        park_id="wind_farm_a",
        channel=AlertChannel.VOICE_CALL,
        health_status="CRITICAL",
        days_to_failure=1.0,
        fault_probability=0.9,
        suspected_failure="Bearing Overheating",
        recommended_action="Controlled shutdown.",
        mwh=15.0,
        assigned_crew="Alpha Team",
    )
    assert "Alpha Team" in payload["speech_text"]
    assert "CRITICAL" in payload["decision_reason"]
