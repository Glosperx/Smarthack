"""
# Unit tests for voice and email notification clients

Validates text-to-speech emergency phone calls and work ticket email dispatching.
"""

from smarthack.clients.email_client import EmailNotificationClient, get_default_email_client
from smarthack.clients.voice_client import VoiceNotificationClient, get_default_voice_client


def test_voice_notification_dispatch() -> None:
    """Verify voice call dispatching and history recording."""
    client = VoiceNotificationClient()
    client.clear_history()

    resp = client.dispatch_emergency_call(
        phone_number="+1-555-0101",
        crew_name="Alpha Response Team",
        turbine_id=0,
        park_id="wind_farm_a",
        message="Generator bearing thermal runaway detected.",
        lead_time_hours=12.5,
    )

    assert resp["status"] == "COMPLETED"
    assert resp["turbine_id"] == 0
    assert "Alpha Response Team" in resp["synthesized_speech"]
    assert "CRITICAL" in resp["synthesized_speech"]

    history = client.get_call_history()
    assert len(history) == 1
    assert history[0]["call_id"] == resp["call_id"]

    client.clear_history()
    assert len(client.get_call_history()) == 0


def test_email_notification_dispatch() -> None:
    """Verify email ticket dispatching and history recording."""
    client = EmailNotificationClient()
    client.clear_history()

    resp = client.dispatch_work_ticket(
        recipient_email="alpha@windfarma.com",
        crew_name="Alpha Response Team",
        turbine_id=1,
        park_id="wind_farm_a",
        subject="[WARNING] Minor hydraulic pressure anomaly",
        body="Telemetry shows gradual pressure drop.",
        diagnostics={"risk_score": 0.45},
    )

    assert resp["status"] == "DELIVERED"
    assert resp["turbine_id"] == 1
    assert resp["diagnostics"]["risk_score"] == 0.45

    history = client.get_email_history()
    assert len(history) == 1
    assert history[0]["ticket_id"] == resp["ticket_id"]

    client.clear_history()
    assert len(client.get_email_history()) == 0


def test_notification_singletons() -> None:
    """Verify singleton accessors."""
    v1 = get_default_voice_client()
    v2 = get_default_voice_client()
    assert v1 is v2

    e1 = get_default_email_client()
    e2 = get_default_email_client()
    assert e1 is e2
