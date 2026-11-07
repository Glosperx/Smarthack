"""
# Phone call

Phones on-call and reads the spoken message in Romanian, through the provider named by
`CALL_PROVIDER`:

- `twilio`: `calls.create` with inline TwiML, `<Say>` in ro-RO, answering machine detection
  (`MachineDetection=Enable`) before the message starts.
- `infobip`: `POST /tts/3/advanced` with the text, language `ro` and a Romanian voice.
  Answering machine detection is off unless `INFOBIP_MACHINE_DETECTION` is set, because
  Infobip enables it per account on request and otherwise rejects the call.

There is no webhook with either: the outcome is read back by polling (Twilio: the call
resource; Infobip: `GET /tts/3/logs`, which can be read repeatedly, then the one-time
`GET /voice/1/reports` for `answeredBy` and the duration). Outcomes are normalised to Twilio's
vocabulary: `completed`, `busy`, `no-answer`, `failed`, `canceled`; `answered_by` is
`human`, `machine...`, `unknown`, or None when nothing detected it.

Gates, in order, before a call is placed:
1. the number must be in `ALLOWED_PHONES`;
2. the alert must have had fewer than `MAX_CALLS_PER_ALERT` calls (see `alerting.state`);
3. with `DRY_RUN` (the default) the call is only logged.

The following can be imported from this module:
- `TERMINAL_STATUSES`
- `CallProgress`
- `CallProvider`
- `CallRejected`
- `CallResult`
- `InfobipProvider`
- `TwilioProvider`
- `build_twiml`
- `check_account`
- `make_provider`
- `place_call`
- `wait_for_call`
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import time
from typing import Any, Protocol

from alerting import config
from alerting.allowlist import Allowlist, RecipientNotAllowed, mask_phone
from alerting.state import MAX_CALLS_PER_ALERT, StateStore

__all__ = [
    "TERMINAL_STATUSES",
    "CallProgress",
    "CallProvider",
    "CallRejected",
    "CallResult",
    "InfobipProvider",
    "TwilioProvider",
    "build_twiml",
    "check_account",
    "make_provider",
    "place_call",
    "wait_for_call",
]

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"completed", "busy", "no-answer", "failed", "canceled"})

_TIME_LIMIT_SECONDS = 120
_REPEAT = 2


@dataclass(frozen=True)
class CallResult:
    """
    What happened to one call. `recipient` is masked.

    `status` is a normalised call status, or one of ours: `dry_run`, `refused`,
    `limit_reached`, `rejected` (the provider refused to create the call).
    """

    recipient: str
    status: str
    answered_by: str | None = None
    duration: int | None = None
    sid: str | None = None
    detail: str = ""

    @property
    def answered(self) -> bool:
        """
        Whether a person took the call.

        `answered_by` None means no detection ran (Infobip without it), so a completed call
        counts; `unknown`, a machine or a fax do not.

        :returns: True for `completed` answered by `human` or with no detection.
        """
        if self.status != "completed":
            return False
        return self.answered_by is None or self.answered_by == "human"


@dataclass(frozen=True)
class CallProgress:
    """One look at a call in progress, in the normalised vocabulary."""

    status: str
    answered_by: str | None = None
    duration: int | None = None
    detail: str = ""


class CallRejected(Exception):
    """The provider refused to create the call; nobody was phoned."""


class CallProvider(Protocol):
    """What `place_call` and `wait_for_call` need from a provider."""

    name: str

    def describe(self) -> str:
        """Caller ID (masked) and voice, for logs."""
        ...

    def start(self, to: str, text: str) -> tuple[str, str]:
        """Place the call; return its id and initial status, or raise `CallRejected`."""
        ...

    def poll(self, call_id: str) -> CallProgress:
        """Read the call's current state."""
        ...


def build_twiml(text: str, settings: config.TwilioSettings, repeat: int = _REPEAT) -> str:
    """
    TwiML that reads `text` `repeat` times, with short pauses around it.

    :param text: The spoken message.
    :param settings: Supplies the voice and language.
    :param repeat: How many times to say it. Defaults to 2, in case the start is missed.

    :returns: The TwiML document.
    """
    from twilio.twiml.voice_response import VoiceResponse

    response = VoiceResponse()
    response.pause(length=1)
    for _ in range(repeat):
        response.say(text, voice=settings.voice, language=settings.language)
        response.pause(length=1)
    return str(response)


class TwilioProvider:
    """Twilio Programmable Voice."""

    name = "twilio"

    def __init__(self, settings: config.TwilioSettings, client: Any = None) -> None:
        """
        :param settings: Credentials and call options.
        :param client: A Twilio client. Defaults to None, meaning one built from `settings`.
        """
        if client is None:
            from twilio.rest import Client

            client = Client(settings.account_sid, settings.auth_token)
        self.settings = settings
        self.client = client

    def describe(self) -> str:
        """
        :returns: Caller ID (masked) and voice.
        """
        return f"twilio from {mask_phone(self.settings.caller_id)}, voice {self.settings.voice}"

    def start(self, to: str, text: str) -> tuple[str, str]:
        """
        Create the call with inline TwiML and answering machine detection.

        :param to: E.164 number.
        :param text: The spoken message.

        :returns: The call SID and its status.
        :raises CallRejected: When Twilio refuses the request.
        """
        from twilio.base.exceptions import TwilioRestException

        try:
            call = self.client.calls.create(
                to=to,
                from_=self.settings.caller_id,
                twiml=build_twiml(text, self.settings),
                timeout=self.settings.ring_timeout,
                time_limit=_TIME_LIMIT_SECONDS,
                machine_detection="Enable",
                machine_detection_timeout=self.settings.machine_detection_timeout,
            )
        except TwilioRestException as error:
            raise CallRejected(f"Twilio {error.code}: {error.msg}") from error
        return call.sid, call.status

    def poll(self, call_id: str) -> CallProgress:
        """
        Fetch the call resource.

        :param call_id: The call SID.

        :returns: Status, `answered_by` and duration as Twilio reports them.
        """
        call = self.client.calls(call_id).fetch()
        duration = int(call.duration) if call.duration not in (None, "") else None
        return CallProgress(call.status, call.answered_by, duration)


# Infobip error ids for answering machine detection; 5000/5001 are deprecated but still sent.
_INFOBIP_HUMAN_ERRORS = {5000, 10003}
_INFOBIP_MACHINE_ERRORS = {5001, 10002}
_INFOBIP_NO_ANSWER_ERRORS = {10200}
_INFOBIP_TERMINAL_GROUPS = {"DELIVERED", "UNDELIVERABLE", "EXPIRED", "REJECTED"}


def _infobip_failure(status: dict[str, Any], error: dict[str, Any]) -> str:
    name = str(error.get("name") or status.get("name") or "").upper()
    if "BUSY" in name:
        return "busy"
    if error.get("id") in _INFOBIP_NO_ANSWER_ERRORS or "ANSWER" in name:
        return "no-answer"
    return "failed"


class InfobipProvider:
    """Infobip Voice: advanced text-to-speech message, read back from logs and reports."""

    name = "infobip"

    def __init__(self, settings: config.InfobipSettings, http: Any = None) -> None:
        """
        :param settings: Credentials and call options.
        :param http: A `requests.Session`-like object. Defaults to None, meaning a new one.
        """
        if http is None:
            import requests

            http = requests.Session()
        self.settings = settings
        self.http = http

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"App {self.settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        response = self.http.get(
            f"{self.settings.base_url}{path}", params=params, headers=self._headers(), timeout=15
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    def describe(self) -> str:
        """
        :returns: Caller ID (masked, or the trial sender) and voice.
        """
        caller_id = self.settings.caller_id
        sender = mask_phone(f"+{caller_id}") if caller_id else "the trial's test sender"
        return f"infobip from {sender}, voice {self.settings.voice}"

    def start(self, to: str, text: str) -> tuple[str, str]:
        """
        Send one advanced voice message; the text is said twice, with a pause between.

        :param to: E.164 number; the leading `+` is dropped, as Infobip expects.
        :param text: The spoken message.

        :returns: The message id and `queued`.
        :raises CallRejected: On an HTTP error or a `REJECTED` status.
        """
        # Each comma is a 0.5 s pause in Infobip text-to-speech.
        spoken = " ,,,, Repet. ,, ".join([text] * _REPEAT)
        message: dict[str, Any] = {
            "destinations": [{"to": to.lstrip("+")}],
            "text": spoken,
            "language": self.settings.language,
            "voice": {"name": self.settings.voice},
            "ringTimeout": self.settings.ring_timeout,
            "callTimeout": _TIME_LIMIT_SECONDS,
            "pause": 1,
        }
        if self.settings.caller_id:
            message["from"] = self.settings.caller_id
        if self.settings.machine_detection:
            message["machineDetection"] = self.settings.machine_detection
        response = self.http.post(
            f"{self.settings.base_url}/tts/3/advanced",
            json={"messages": [message]},
            headers=self._headers(),
            timeout=15,
        )
        if response.status_code >= 400:
            try:
                text_error = response.json()["requestError"]["serviceException"]["text"]
            except (ValueError, KeyError, TypeError):
                text_error = response.reason
            raise CallRejected(f"Infobip HTTP {response.status_code}: {text_error}")
        sent = response.json()["messages"][0]
        status = sent.get("status", {})
        if status.get("groupName") == "REJECTED":
            raise CallRejected(
                f"Infobip {status.get('name')}: {status.get('description', '')}".strip()
            )
        return sent["messageId"], "queued"

    def poll(self, call_id: str) -> CallProgress:
        """
        Read the message log; once it is final, read the one-time delivery report too.

        :param call_id: The message id.

        :returns: The normalised status, `answered_by` (None without detection) and duration.
        """
        logs = self._get("/tts/3/logs", {"messageId": call_id}).get("results", [])
        if not logs:
            return CallProgress("queued")
        log = logs[0]
        status, error = log.get("status") or {}, log.get("error") or {}
        group = status.get("groupName", "")
        if group not in _INFOBIP_TERMINAL_GROUPS:
            return CallProgress("in-progress")

        detail = f"{status.get('name', '')} {error.get('name', '')}".strip()
        if group == "REJECTED":
            # Refused before dialling (e.g. a trial destination not on the allowed list).
            return CallProgress("failed", None, 0, f"{detail}: {error.get('description', '')}")
        call = self._report(call_id)
        duration = call.get("duration", log.get("duration"))
        detected = str(call.get("answeredBy") or "").lower() or None
        if detected is None and error.get("id") in _INFOBIP_HUMAN_ERRORS:
            detected = "human"
        if detected is None and error.get("id") in _INFOBIP_MACHINE_ERRORS:
            detected = "machine"
        if group == "DELIVERED":
            return CallProgress("completed", detected, duration, detail)
        return CallProgress(_infobip_failure(status, error), detected, duration, detail)

    def _report(self, call_id: str) -> dict[str, Any]:
        """The `voiceCall` part of the one-time delivery report; empty if unavailable."""
        import requests

        try:
            reports = self._get("/voice/1/reports", {"messageId": call_id}).get("results", [])
        except requests.HTTPError as error:
            # An API key without the reports scope gets 403; the logs are enough to go on.
            logger.warning("Infobip delivery report unavailable, using logs only: %s", error)
            return {}
        voice_call: dict[str, Any] = (reports[0].get("voiceCall") or {}) if reports else {}
        return voice_call

    def voices(self) -> list[dict[str, Any]]:
        """
        Romanian voices the account can use (read-only).

        :returns: The `voices` list of `GET /tts/3/voices/ro`, neural ones included.
        """
        data = self._get(f"/tts/3/voices/{self.settings.language}", {"includeNeural": "true"})
        voices: list[dict[str, Any]] = data.get("voices", [])
        return voices


def make_provider(env: Mapping[str, str] | None = None) -> CallProvider:
    """
    Build the provider named by `CALL_PROVIDER`.

    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.

    :returns: A `TwilioProvider` or an `InfobipProvider`.
    """
    env = config.environment() if env is None else env
    if config.call_provider(env) == "infobip":
        return InfobipProvider(config.infobip_settings(env))
    return TwilioProvider(config.twilio_settings(env))


def place_call(
    alert_id: str,
    to: str,
    text: str,
    env: Mapping[str, str] | None = None,
    provider: CallProvider | None = None,
    store: StateStore | None = None,
) -> CallResult:
    """
    Start one call, subject to the allowlist, the per-alert cap and `DRY_RUN`.

    :param alert_id: The alert the call is for; the cap is counted per alert.
    :param to: The number to call, E.164.
    :param text: The spoken message.
    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.
    :param provider: Who places the call. Defaults to None, meaning `make_provider(env)`.
    :param store: Where calls are counted. Defaults to None, meaning `state/alerts.json`.

    :returns: The call as the provider accepted it (usually `queued`), or why it was not placed.
    """
    env = config.environment() if env is None else env
    store = StateStore() if store is None else store
    masked = mask_phone(to)
    try:
        number = Allowlist.from_env(env).check_phone(to)
    except RecipientNotAllowed as refusal:
        logger.warning("call refused: %s", refusal)
        return CallResult(masked, "refused", detail=str(refusal))
    made = store.calls_made(alert_id)
    if made >= MAX_CALLS_PER_ALERT:
        detail = f"{made} calls already placed for {alert_id}, limit {MAX_CALLS_PER_ALERT}"
        logger.warning("call not placed: %s", detail)
        return CallResult(masked, "limit_reached", detail=detail)

    provider = make_provider(env) if provider is None else provider
    if config.dry_run(env):
        logger.info(
            "DRY_RUN: call to %s via %s (not placed)\n%s", masked, provider.describe(), text
        )
        return CallResult(masked, "dry_run")
    try:
        call_id, status = provider.start(number, text)
    except CallRejected as rejection:
        logger.error("call to %s rejected: %s", masked, rejection)
        return CallResult(masked, "rejected", detail=str(rejection))
    store.add_call(alert_id, call_id, masked, status)
    logger.info("call %s to %s accepted via %s: %s", call_id, masked, provider.name, status)
    return CallResult(masked, status, sid=call_id)


def wait_for_call(
    alert_id: str,
    placed: CallResult,
    env: Mapping[str, str] | None = None,
    provider: CallProvider | None = None,
    store: StateStore | None = None,
    poll_seconds: float = 3.0,
    max_wait_seconds: float = 300.0,
    sleep: Callable[[float], None] = time.sleep,
) -> CallResult:
    """
    Poll a placed call until it ends, and store the outcome.

    :param alert_id: The alert the call is for.
    :param placed: The result of `place_call`; returned as is when no call was placed.
    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.
    :param provider: Who placed the call. Defaults to None, meaning `make_provider(env)`.
    :param store: Where the outcome is stored. Defaults to None, meaning `state/alerts.json`.
    :param poll_seconds: Seconds between polls.
    :param max_wait_seconds: Give up waiting after this long; the last status is returned.
    :param sleep: The sleep function, replaceable in tests.

    :returns: The final status, `answered_by` and duration in seconds.
    """
    if placed.sid is None:
        return placed
    store = StateStore() if store is None else store
    provider = make_provider(env) if provider is None else provider
    waited = 0.0
    while True:
        progress = provider.poll(placed.sid)
        if progress.status in TERMINAL_STATUSES or waited >= max_wait_seconds:
            break
        sleep(poll_seconds)
        waited += poll_seconds
    detail = progress.detail
    if progress.status not in TERMINAL_STATUSES:
        detail = "still in progress when polling stopped"
    result = CallResult(
        placed.recipient,
        progress.status,
        progress.answered_by,
        progress.duration,
        placed.sid,
        detail,
    )
    store.update_call(
        alert_id,
        placed.sid,
        status=result.status,
        answered_by=result.answered_by,
        duration=result.duration,
    )
    logger.info(
        "call %s ended: %s, answered_by=%s, %ss %s",
        placed.sid,
        result.status,
        result.answered_by,
        result.duration,
        detail,
    )
    return result


def _check_twilio(env: Mapping[str, str], provider: TwilioProvider) -> dict[str, Any]:
    from twilio.base.exceptions import TwilioRestException

    settings, client = provider.settings, provider.client
    account = client.api.v2010.accounts(settings.account_sid).fetch()
    verified = {item.phone_number for item in client.outgoing_caller_ids.list(limit=50)}
    owned = {item.phone_number for item in client.incoming_phone_numbers.list(limit=50)}
    try:
        romania: bool | str = (
            client.voice.v1.dialing_permissions.countries("RO").fetch().low_risk_numbers_enabled
        )
    except TwilioRestException as error:
        # Trial accounts cannot read Geo Permissions through the API.
        romania = f"unknown, check in the console ({error.msg})"
    allowed = Allowlist.from_env(env).phones
    return {
        "provider": "twilio",
        "account_type": account.type,
        "account_status": account.status,
        "verified_caller_ids": sorted(mask_phone(number) for number in verified),
        "twilio_numbers": sorted(mask_phone(number) for number in owned),
        "caller_id_usable": settings.caller_id in verified | owned,
        "allowed_numbers_verified": {mask_phone(n): n in verified | owned for n in allowed},
        "romania_low_risk_enabled": romania,
        "voice": settings.voice,
    }


def _check_infobip(provider: InfobipProvider) -> dict[str, Any]:
    voices = provider.voices()
    return {
        "provider": "infobip",
        "credentials": "ok",
        "romanian_voices": [
            f"{v.get('name')} ({v.get('gender')}, {'neural' if v.get('isNeural') else 'standard'})"
            for v in voices
        ],
        "voice": provider.settings.voice,
        "voice_available": any(v.get("name") == provider.settings.voice for v in voices),
        "machine_detection": provider.settings.machine_detection or "off",
    }


def check_account(
    env: Mapping[str, str] | None = None, provider: CallProvider | None = None
) -> dict[str, Any]:
    """
    Read-only look at the call provider before a real call: nothing is created or changed.

    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.
    :param provider: The provider. Defaults to None, meaning `make_provider(env)`.

    :returns: For Twilio: account type, masked verified and owned numbers, Romania in Geo
        Permissions. For Infobip: whether the credentials work and the Romanian voices.
    """
    env = config.environment() if env is None else env
    provider = make_provider(env) if provider is None else provider
    if isinstance(provider, InfobipProvider):
        return _check_infobip(provider)
    if isinstance(provider, TwilioProvider):
        return _check_twilio(env, provider)
    raise TypeError(f"no account check for {type(provider).__name__}")
