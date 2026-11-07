"""Tests for the phone call gates, polling and state, against fake Twilio and Infobip APIs."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import requests
from twilio.base.exceptions import TwilioRestException

from alerting.caller import (
    CallResult,
    InfobipProvider,
    TwilioProvider,
    build_twiml,
    check_account,
    make_provider,
    place_call,
    wait_for_call,
)
from alerting.config import call_provider, infobip_settings, twilio_settings
from alerting.state import MAX_CALLS_PER_ALERT, StateStore

TO = "+40700000001"
ENV = {
    "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
    "TWILIO_AUTH_TOKEN": "secret-token",
    "SENDER_PHONE": "+40700000099",
    "ALLOWED_PHONES": TO,
}
LIVE = ENV | {"DRY_RUN": "false"}
INFOBIP_ENV = {
    "CALL_PROVIDER": "infobip",
    "INFOBIP_API_KEY": "secret-key",
    "INFOBIP_BASE_URL": "abc123.api.infobip.com/",
    "ALLOWED_PHONES": TO,
}


# --- Fake Twilio --------------------------------------------------------------


@dataclass
class FakeCall:
    sid: str
    status: str
    answered_by: str | None = None
    duration: str | None = None


@dataclass
class FakeCalls:
    """Stands in for `client.calls`: `create(...)` and `calls(sid).fetch()`."""

    timeline: list[FakeCall] = field(default_factory=list)
    created: list[dict[str, Any]] = field(default_factory=list)
    error: TwilioRestException | None = None

    def create(self, **kwargs: Any) -> FakeCall:
        if self.error is not None:
            raise self.error
        self.created.append(kwargs)
        return FakeCall(sid=f"CA{len(self.created):032d}", status="queued")

    def __call__(self, sid: str) -> "FakeCalls":
        return self

    def fetch(self) -> FakeCall:
        return self.timeline.pop(0) if len(self.timeline) > 1 else self.timeline[0]


class FakeClient:
    def __init__(self, calls: FakeCalls) -> None:
        self.calls = calls


def _twilio(calls: FakeCalls) -> TwilioProvider:
    return TwilioProvider(twilio_settings(ENV), client=FakeClient(calls))


# --- Fake Infobip HTTP ------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body
        self.reason = "Bad Request" if status_code >= 400 else "OK"

    def json(self) -> dict[str, Any]:
        return self.body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


@dataclass
class FakeHttp:
    """Stands in for `requests.Session`; GET answers come from per-path queues."""

    post_response: FakeResponse = field(
        default_factory=lambda: FakeResponse(
            200,
            {
                "messages": [
                    {
                        "to": "40700000001",
                        "messageId": "M1",
                        "status": {"groupName": "PENDING", "name": "PENDING_ACCEPTED"},
                    }
                ]
            },
        )
    )
    gets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    posted: list[dict[str, Any]] = field(default_factory=list)
    requested: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    forbidden: set[str] = field(default_factory=set)

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> Any:
        self.posted.append({"url": url, "json": json, "headers": headers})
        return self.post_response

    def get(self, url: str, params: dict[str, str], headers: dict[str, str], timeout: int) -> Any:
        path = url.split(".com", 1)[1]
        self.requested.append((path, params))
        if path in self.forbidden:
            return FakeResponse(403, {})
        queue = self.gets.get(path, [{"results": []}])
        return FakeResponse(200, queue.pop(0) if len(queue) > 1 else queue[0])


def _infobip(http: FakeHttp, env: dict[str, str] = INFOBIP_ENV) -> InfobipProvider:
    return InfobipProvider(infobip_settings(env), http=http)


def _log(group: str, name: str = "", error: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "messageId": "M1",
        "duration": 31,
        "status": {"groupName": group, "name": name},
    }
    if error is not None:
        result["error"] = error
    return {"results": [result]}


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "alerts.json")


# --- Settings ---------------------------------------------------------------------


def test_twiml_says_the_text_twice_in_romanian() -> None:
    twiml = build_twiml("Turbina șapte & co.", twilio_settings(ENV))
    assert twiml.count('<Say language="ro-RO" voice="Google.ro-RO-Wavenet-B">') == 2
    assert "Turbina șapte &amp; co." in twiml


def test_voice_is_configurable_and_secrets_hidden() -> None:
    settings = twilio_settings(ENV | {"TWILIO_VOICE": "Polly.Carmen"})
    assert settings.voice == "Polly.Carmen"
    assert "secret-token" not in repr(settings)
    assert "secret-key" not in repr(infobip_settings(INFOBIP_ENV))


def test_missing_credentials_are_named() -> None:
    with pytest.raises(ValueError, match="TWILIO_AUTH_TOKEN"):
        twilio_settings({"TWILIO_ACCOUNT_SID": "AC1", "SENDER_PHONE": "+40700000099"})
    with pytest.raises(ValueError, match="INFOBIP_API_KEY"):
        infobip_settings({"INFOBIP_BASE_URL": "x.api.infobip.com"})


def test_infobip_defaults() -> None:
    settings = infobip_settings(INFOBIP_ENV)
    assert settings.base_url == "https://abc123.api.infobip.com"
    assert (settings.voice, settings.language, settings.machine_detection) == ("Carmen", "ro", "")
    assert settings.caller_id == ""


def test_provider_choice() -> None:
    assert call_provider({}) == "twilio"
    assert call_provider({"CALL_PROVIDER": "Infobip"}) == "infobip"
    with pytest.raises(ValueError, match="CALL_PROVIDER"):
        call_provider({"CALL_PROVIDER": "vonage"})
    assert isinstance(make_provider(INFOBIP_ENV), InfobipProvider)
    with pytest.raises(ValueError, match="INFOBIP_MACHINE_DETECTION"):
        infobip_settings(INFOBIP_ENV | {"INFOBIP_MACHINE_DETECTION": "maybe"})


# --- Gates (provider-independent) ---------------------------------------------------


def test_dry_run_is_the_default_and_creates_nothing(store: StateStore) -> None:
    calls = FakeCalls()
    result = place_call("A1", TO, "text", env=ENV, provider=_twilio(calls), store=store)
    assert result.status == "dry_run" and calls.created == []
    assert store.calls_made("A1") == 0


def test_number_outside_the_allowlist_is_refused(store: StateStore) -> None:
    calls = FakeCalls()
    result = place_call(
        "A1", "+40711111111", "text", env=LIVE, provider=_twilio(calls), store=store
    )
    assert result.status == "refused" and calls.created == []
    assert "11111" not in result.detail


def test_no_more_than_three_calls_per_alert(store: StateStore) -> None:
    calls = FakeCalls()
    provider = _twilio(calls)
    statuses = [
        place_call("A1", TO, "text", env=LIVE, provider=provider, store=store).status
        for _ in range(MAX_CALLS_PER_ALERT + 1)
    ]
    assert statuses == ["queued"] * MAX_CALLS_PER_ALERT + ["limit_reached"]
    assert len(calls.created) == MAX_CALLS_PER_ALERT
    assert place_call("A2", TO, "text", env=LIVE, provider=provider, store=store).status == "queued"


def test_the_cap_survives_a_new_process(store: StateStore, tmp_path: Path) -> None:
    provider = _twilio(FakeCalls())
    for _ in range(MAX_CALLS_PER_ALERT):
        place_call("A1", TO, "text", env=LIVE, provider=provider, store=store)
    fresh = StateStore(tmp_path / "alerts.json")
    result = place_call("A1", TO, "t", env=LIVE, provider=provider, store=fresh)
    assert result.status == "limit_reached"


def test_nothing_to_wait_for_when_no_call_was_placed(store: StateStore) -> None:
    placed = CallResult("+407******01", "refused")
    assert wait_for_call("A1", placed, provider=_twilio(FakeCalls()), store=store) is placed


def test_state_marks_dispatch(store: StateStore) -> None:
    assert not store.is_dispatched("A1")
    store.mark_dispatched("A1", {"email": []})
    assert store.is_dispatched("A1") and store.record("A1")["summary"] == {"email": []}


# --- Twilio -------------------------------------------------------------------------


def test_twilio_call_uses_inline_twiml_amd_and_the_caller_id(store: StateStore) -> None:
    calls = FakeCalls()
    result = place_call("A1", TO, "text", env=LIVE, provider=_twilio(calls), store=store)
    assert result.status == "queued" and result.sid is not None
    created = calls.created[0]
    assert created["to"] == TO and created["from_"] == "+40700000099"
    assert created["machine_detection"] == "Enable"
    assert created["twiml"].startswith("<?xml") and "url" not in created
    assert store.calls_made("A1") == 1


def test_twilio_rejection_is_reported_and_not_counted(store: StateStore) -> None:
    error = TwilioRestException(400, "/Calls", msg="The number is unverified", code=21219)
    provider = _twilio(FakeCalls(error=error))
    result = place_call("A1", TO, "text", env=LIVE, provider=provider, store=store)
    assert result.status == "rejected" and "21219" in result.detail
    assert store.calls_made("A1") == 0


@pytest.mark.parametrize(
    ("final", "answered"),
    [
        (FakeCall("CA1", "completed", "human", "31"), True),
        (FakeCall("CA1", "completed", "machine_start", "25"), False),
        (FakeCall("CA1", "completed", "unknown", "30"), False),
        (FakeCall("CA1", "no-answer", None, "0"), False),
        (FakeCall("CA1", "busy", None, "0"), False),
        (FakeCall("CA1", "failed", None, None), False),
    ],
)
def test_twilio_polling_waits_for_the_end_and_judges_the_answer(
    store: StateStore, final: FakeCall, answered: bool
) -> None:
    timeline = [FakeCall("CA1", "queued"), FakeCall("CA1", "ringing"), final]
    placed = CallResult("+407******01", "queued", sid="CA1")
    store.add_call("A1", "CA1", placed.recipient, "queued")
    sleeps: list[float] = []
    result = wait_for_call(
        "A1",
        placed,
        provider=_twilio(FakeCalls(timeline=timeline)),
        store=store,
        sleep=sleeps.append,
    )
    assert (result.status, result.answered) == (final.status, answered)
    assert len(sleeps) == 2
    assert store.record("A1")["calls"][0]["status"] == final.status


def test_polling_gives_up_after_max_wait(store: StateStore) -> None:
    provider = _twilio(FakeCalls(timeline=[FakeCall("CA1", "in-progress")]))
    placed = CallResult("+407******01", "queued", sid="CA1")
    result = wait_for_call(
        "A1", placed, provider=provider, store=store, sleep=lambda s: None, max_wait_seconds=9
    )
    assert result.status == "in-progress" and "still in progress" in result.detail


# --- Infobip ------------------------------------------------------------------------


def test_infobip_request_matches_the_api(store: StateStore) -> None:
    http = FakeHttp()
    env = INFOBIP_ENV | {"DRY_RUN": "false"}
    result = place_call("A1", TO, "Bună ziua.", env=env, provider=_infobip(http), store=store)
    assert (result.status, result.sid) == ("queued", "M1")
    request = http.posted[0]
    assert request["url"] == "https://abc123.api.infobip.com/tts/3/advanced"
    assert request["headers"]["Authorization"] == "App secret-key"
    message = request["json"]["messages"][0]
    assert message["destinations"] == [{"to": "40700000001"}]
    assert message["language"] == "ro" and message["voice"] == {"name": "Carmen"}
    assert message["text"].count("Bună ziua.") == 2
    assert "machineDetection" not in message and "from" not in message
    assert store.calls_made("A1") == 1


def test_infobip_optional_caller_id_and_detection() -> None:
    http = FakeHttp()
    env = INFOBIP_ENV | {"INFOBIP_FROM": "+40 700 000 099", "INFOBIP_MACHINE_DETECTION": "hangup"}
    _infobip(http, env).start(TO, "x")
    message = http.posted[0]["json"]["messages"][0]
    assert message["from"] == "40700000099" and message["machineDetection"] == "hangup"


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            FakeResponse(401, {"requestError": {"serviceException": {"text": "Invalid login"}}}),
            "Infobip HTTP 401: Invalid login",
        ),
        (
            FakeResponse(
                200,
                {
                    "messages": [
                        {
                            "messageId": "M1",
                            "status": {
                                "groupName": "REJECTED",
                                "name": "REJECTED_DESTINATION_NOT_REGISTERED",
                                "description": "Destination not registered",
                            },
                        }
                    ]
                },
            ),
            "REJECTED_DESTINATION_NOT_REGISTERED",
        ),
    ],
)
def test_infobip_rejection_is_reported_and_not_counted(
    store: StateStore, response: FakeResponse, expected: str
) -> None:
    http = FakeHttp(post_response=response)
    env = INFOBIP_ENV | {"DRY_RUN": "false"}
    result = place_call("A1", TO, "x", env=env, provider=_infobip(http), store=store)
    assert result.status == "rejected" and expected in result.detail
    assert store.calls_made("A1") == 0


@pytest.mark.parametrize(
    ("final_log", "report", "status", "answered_by", "answered"),
    [
        (_log("DELIVERED", "DELIVERED_TO_HANDSET"), {}, "completed", None, True),
        (
            _log("DELIVERED", "DELIVERED_TO_HANDSET"),
            {"voiceCall": {"answeredBy": "MACHINE", "duration": 20}},
            "completed",
            "machine",
            False,
        ),
        (
            _log("DELIVERED", "DELIVERED_TO_HANDSET", {"id": 10003, "name": "HUMAN_DETECTED"}),
            {},
            "completed",
            "human",
            True,
        ),
        (
            _log(
                "UNDELIVERABLE", "UNDELIVERABLE_NOT_DELIVERED", {"id": 10200, "name": "NO_ANSWER"}
            ),
            {},
            "no-answer",
            None,
            False,
        ),
        (
            _log(
                "UNDELIVERABLE", "UNDELIVERABLE_NOT_DELIVERED", {"id": 27, "name": "EC_USER_BUSY"}
            ),
            {},
            "busy",
            None,
            False,
        ),
        (
            _log("EXPIRED", "EXPIRED_EXPIRED", {"id": 1, "name": "EC_UNKNOWN_SUBSCRIBER"}),
            {},
            "failed",
            None,
            False,
        ),
    ],
)
def test_infobip_polling_reads_logs_then_the_one_time_report(
    store: StateStore,
    final_log: dict[str, Any],
    report: dict[str, Any],
    status: str,
    answered_by: str | None,
    answered: bool,
) -> None:
    http = FakeHttp(
        gets={
            "/tts/3/logs": [{"results": []}, _log("PENDING", "PENDING_ENROUTE"), final_log],
            "/voice/1/reports": [{"results": [report]} if report else {"results": []}],
        }
    )
    placed = CallResult("+407******01", "queued", sid="M1")
    store.add_call("A1", "M1", placed.recipient, "queued")
    sleeps: list[float] = []
    result = wait_for_call("A1", placed, provider=_infobip(http), store=store, sleep=sleeps.append)
    assert (result.status, result.answered_by, result.answered) == (status, answered_by, answered)
    assert len(sleeps) == 2
    report_requests = [path for path, _ in http.requested if path == "/voice/1/reports"]
    assert report_requests == ["/voice/1/reports"]
    assert all(params == {"messageId": "M1"} for path, params in http.requested if "logs" in path)


def test_infobip_check_lists_romanian_voices() -> None:
    voices = {
        "voices": [
            {"name": "Carmen", "gender": "female", "isNeural": False},
            {"name": "Emil", "gender": "male", "isNeural": True},
        ]
    }
    http = FakeHttp(gets={"/tts/3/voices/ro": [voices]})
    report = check_account(env=INFOBIP_ENV, provider=_infobip(http))
    assert report["voice_available"] is True
    assert report["romanian_voices"] == ["Carmen (female, standard)", "Emil (male, neural)"]
    assert http.requested == [("/tts/3/voices/ro", {"includeNeural": "true"})]


def test_infobip_trial_rejection_after_acceptance_is_a_failure(store: StateStore) -> None:
    rejected = _log(
        "REJECTED",
        "REJECTED_DESTINATION_NOT_REGISTERED",
        {"id": 579, "name": "EC_DEST_ADDRESS_NOT_IN_SMS_DEMO", "description": "Not in whitelist"},
    )
    http = FakeHttp(gets={"/tts/3/logs": [rejected]})
    placed = CallResult("+407******01", "queued", sid="M1")
    store.add_call("A1", "M1", placed.recipient, "queued")
    result = wait_for_call("A1", placed, provider=_infobip(http), store=store, sleep=lambda s: None)
    assert (result.status, result.answered) == ("failed", False)
    assert "EC_DEST_ADDRESS_NOT_IN_SMS_DEMO" in result.detail
    assert [path for path, _ in http.requested] == ["/tts/3/logs"]


def test_infobip_report_forbidden_falls_back_to_logs(store: StateStore) -> None:
    http = FakeHttp(
        gets={"/tts/3/logs": [_log("DELIVERED", "DELIVERED_TO_HANDSET")]},
        forbidden={"/voice/1/reports"},
    )
    placed = CallResult("+407******01", "queued", sid="M1")
    store.add_call("A1", "M1", placed.recipient, "queued")
    result = wait_for_call("A1", placed, provider=_infobip(http), store=store, sleep=lambda s: None)
    assert (result.status, result.duration, result.answered) == ("completed", 31, True)
