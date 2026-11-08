"""
# Unit tests for voice and email notification clients

Validates text-to-speech emergency phone calls and work ticket email dispatching.
"""

import re
import sys
import types
from typing import Any

import pytest

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


def _fake_alerting(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[dict[str, Any]]:
    """
    Replace `alerting.dispatch` with a fake, so no test ever phones or emails anyone.

    :param monkeypatch: pytest's monkeypatch.
    :param outcome: What the fake returns, or an exception it raises.

    :returns calls: The `{"alert": ..., "decision": ...}` pairs it was given.
    """
    calls: list[dict[str, Any]] = []

    def dispatch(
        alert: dict[str, Any], decision: dict[str, Any], env: dict[str, str]
    ) -> dict[str, Any]:
        calls.append({"alert": alert, "decision": decision, "env": env})
        if isinstance(outcome, Exception):
            raise outcome
        return dict(outcome)

    module = types.ModuleType("alerting.dispatch")
    module.dispatch = dispatch  # type: ignore[attr-defined]
    config_module = types.ModuleType("alerting.config")
    config_module.environment = lambda: {"DRY_RUN": "false"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "alerting", types.ModuleType("alerting"))
    monkeypatch.setitem(sys.modules, "alerting.config", config_module)
    monkeypatch.setitem(sys.modules, "alerting.dispatch", module)
    return calls


def _call(client: VoiceNotificationClient) -> dict[str, Any]:
    """
    Place one call for turbine 7 of a park.

    :param client: The client under test.

    :returns record: The call record.
    """
    return client.dispatch_emergency_call(
        phone_number="+1-555-0100",
        crew_name="Park Lead",
        turbine_id=7,
        park_id="wind_farm_a",
        message="Gearbox failing.",
        lead_time_hours=29.0,
        fault_probability=0.97,
    )


def test_no_real_call_unless_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """By default the call is only recorded: the alerting module is never reached."""
    calls = _fake_alerting(monkeypatch, {"status": "dispatched"})

    record = _call(VoiceNotificationClient())

    assert "real_call" not in record
    assert calls == []


def test_an_enabled_call_goes_to_the_alerting_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The alert carries the turbine, probability and lead time; the decision asks for a call."""
    monkeypatch.setenv("VOICE_CALLS_ENABLED", "true")
    calls = _fake_alerting(
        monkeypatch,
        {"status": "dispatched", "alert_id": "x", "call": {"stopped": "answered"}, "email": []},
    )

    record = _call(VoiceNotificationClient())

    [sent] = calls
    alert, decision = sent["alert"], sent["decision"]
    assert alert["park"] == "wind_farm_a"
    assert alert["turbines"] == [{"turbine_id": "T07", "probability": 0.97}]
    assert alert["hours_to_failure"] == 29.0
    assert alert["alert_id"] == decision["alert_id"]
    assert sent["env"]["CALL_RETRIES_PER_PERSON"] == "0"  # rings once
    assert sent["env"]["DRY_RUN"] == "false"  # the module's own setting is kept
    assert (decision["severity"], decision["channel"]) == ("critica", "email_si_apel")
    assert record["real_call"]["status"] == "dispatched"
    assert record["real_call"]["call"] == {"stopped": "answered"}
    assert record["status"] == "COMPLETED"


def test_a_failing_provider_does_not_stop_the_sweep(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An error from the alerting module is recorded, not raised."""
    monkeypatch.setenv("VOICE_CALLS_ENABLED", "1")
    _fake_alerting(monkeypatch, RuntimeError("twilio is down"))

    record = _call(VoiceNotificationClient())

    assert record["real_call"] == {"status": "error", "error": "RuntimeError: twilio is down"}
    assert "real voice call for turbine 7 failed" in caplog.text


def test_voice_calls_enabled_reads_only_truthy_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo leaves real calls off."""
    from smarthack import config

    for value, expected in [
        ("true", True),
        ("ON", True),
        ("1", True),
        ("yess", False),
        ("", False),
    ]:
        monkeypatch.setenv("VOICE_CALLS_ENABLED", value)
        assert config.voice_calls_enabled() is expected


def test_the_alert_id_does_not_depend_on_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Park, turbine and minute only: two watchers handling one file reach the same id."""
    monkeypatch.setenv("VOICE_CALLS_ENABLED", "true")
    calls = _fake_alerting(monkeypatch, {"status": "dispatched"})

    _call(VoiceNotificationClient())
    other = VoiceNotificationClient()
    other.dispatch_emergency_call("+1", "x", 8, "wind_farm_a", "m")
    _call(other)

    first, different, again = (c["alert"]["alert_id"] for c in calls)
    assert re.fullmatch(r"SMH-\d{8}T\d{4}-wind_farm_a-T7", first)
    assert different.endswith("-T8")
    assert again[:-3] == first[:-3] or again != first  # the minute may have turned


def _ticket(client: EmailNotificationClient, real_alert: dict[str, Any] | None) -> dict[str, Any]:
    """
    Dispatch one work ticket for turbine 7 of a park.

    :param client: The client under test.
    :param real_alert: What the graph passes for an email-only alert, or None.

    :returns record: The ticket record.
    """
    return client.dispatch_work_ticket(
        recipient_email="crew@x.test",
        crew_name="Alpha",
        turbine_id=7,
        park_id="wind_farm_a",
        subject="s",
        body="b",
        real_alert=real_alert,
    )


_EMAIL_ONLY = {"health_status": "WARNING", "lead_time_hours": 144.0, "fault_probability": 0.45}


def test_no_real_email_unless_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """By default the ticket is only recorded: the alerting module is never reached."""
    calls = _fake_alerting(monkeypatch, {"status": "dispatched"})

    record = _ticket(EmailNotificationClient(), _EMAIL_ONLY)

    assert "real_email" not in record
    assert calls == []


def test_an_enabled_email_only_alert_never_asks_for_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision handed to the module is `doar_email`, so on-call is emailed and not phoned."""
    monkeypatch.setenv("REAL_EMAILS_ENABLED", "true")
    calls = _fake_alerting(monkeypatch, {"status": "dispatched", "alert_id": "x", "email": []})

    record = _ticket(EmailNotificationClient(), _EMAIL_ONLY)

    [sent] = calls
    assert sent["decision"]["channel"] == "doar_email"
    assert sent["decision"]["severity"] == "medie"
    assert sent["alert"]["turbines"] == [{"turbine_id": "T07", "probability": 0.45}]
    assert sent["alert"]["hours_to_failure"] == 144.0
    assert record["real_email"]["status"] == "dispatched"


def test_the_email_that_goes_with_a_call_is_not_sent_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without `real_alert` the module is not reached: the call's own dispatch emails on-call."""
    monkeypatch.setenv("REAL_EMAILS_ENABLED", "true")
    calls = _fake_alerting(monkeypatch, {"status": "dispatched"})

    record = _ticket(EmailNotificationClient(), None)

    assert "real_email" not in record
    assert calls == []


def test_a_failing_mail_backend_does_not_stop_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """An error from the alerting module is recorded, not raised."""
    monkeypatch.setenv("REAL_EMAILS_ENABLED", "true")
    _fake_alerting(monkeypatch, RuntimeError("smtp is down"))

    record = _ticket(EmailNotificationClient(), _EMAIL_ONLY)

    assert record["real_email"] == {"status": "error", "error": "RuntimeError: smtp is down"}
    assert record["status"] == "DELIVERED"


def test_real_emails_enabled_reads_only_truthy_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo leaves real emails off."""
    from smarthack import config

    for value, expected in [("true", True), ("ON", True), ("yess", False), ("", False)]:
        monkeypatch.setenv("REAL_EMAILS_ENABLED", value)
        assert config.real_emails_enabled() is expected
