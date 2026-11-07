"""
# Configuration

The only reader of the environment in this package. A value comes from the process
environment when set there, otherwise from `experiments/alerting/.env`. Values are read on
every call, never at import time, and no function here logs or returns them in an error
message: `.env` holds secrets.

Every accessor takes an optional `env` mapping so tests never depend on the real `.env`.

`DRY_RUN` defaults to true: nothing leaves the machine unless it is explicitly `false`.

The following can be imported from this module:
- `CALL_PROVIDERS`
- `ENV_FILE`
- `InfobipSettings`
- `PACKAGE_ROOT`
- `SmtpSettings`
- `TwilioSettings`
- `allowed_emails`
- `allowed_phones`
- `call_provider`
- `dry_run`
- `environment`
- `infobip_settings`
- `smtp_settings`
- `twilio_settings`
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import dotenv_values

__all__ = [
    "CALL_PROVIDERS",
    "ENV_FILE",
    "InfobipSettings",
    "PACKAGE_ROOT",
    "SmtpSettings",
    "TwilioSettings",
    "allowed_emails",
    "allowed_phones",
    "call_provider",
    "dry_run",
    "environment",
    "infobip_settings",
    "smtp_settings",
    "twilio_settings",
]

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PACKAGE_ROOT / ".env"

CALL_PROVIDERS = ("twilio", "infobip")

_TRUE = {"1", "true", "yes", "da"}
_FALSE = {"0", "false", "no", "nu"}


def environment(env_file: Path | None = ENV_FILE) -> dict[str, str]:
    """
    Merge the `.env` file and the process environment, the process environment winning.

    :param env_file: The dotenv file to read. Defaults to `experiments/alerting/.env`; None
        or a missing file means the process environment alone.

    :returns: A fresh dict of variable names to values.
    """
    values: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    values.update(os.environ)
    return values


def _get(env: Mapping[str, str] | None, name: str, default: str = "") -> str:
    source = environment() if env is None else env
    return source.get(name, default).strip() or default


def dry_run(env: Mapping[str, str] | None = None) -> bool:
    """
    Whether to only show what would be sent. Unset or empty means true.

    :param env: Variables to read. Defaults to None, meaning `environment()`.

    :returns: False only when `DRY_RUN` is explicitly false (`false`, `0`, `no`, `nu`).
    :raises ValueError: When `DRY_RUN` is set to something that is not a boolean.
    """
    value = _get(env, "DRY_RUN", "true").lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError("DRY_RUN must be true or false")


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def allowed_emails(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """
    The only addresses an email may be sent to, lower-cased.

    :param env: Variables to read. Defaults to None, meaning `environment()`.

    :returns: The `ALLOWED_EMAILS` entries; empty when unset, which refuses everyone.
    """
    return frozenset(item.lower() for item in _split(_get(env, "ALLOWED_EMAILS")))


def allowed_phones(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """
    The only numbers that may be called, with spaces and dashes removed.

    :param env: Variables to read. Defaults to None, meaning `environment()`.

    :returns: The `ALLOWED_PHONES` entries; empty when unset, which refuses everyone.
    """
    return frozenset(
        item.replace(" ", "").replace("-", "") for item in _split(_get(env, "ALLOWED_PHONES"))
    )


@dataclass(frozen=True)
class SmtpSettings:
    """Where and how emails are sent. The password never appears in `repr`."""

    backend: str
    host: str
    port: int
    starttls: bool
    sender: str
    sender_name: str
    username: str = ""
    password: str = field(default="", repr=False)


def smtp_settings(env: Mapping[str, str] | None = None) -> SmtpSettings:
    """
    The SMTP server chosen by `EMAIL_BACKEND`: `mailpit` (default, local) or `gmail`.

    :param env: Variables to read. Defaults to None, meaning `environment()`.

    :returns: The settings for that backend.
    :raises ValueError: When the backend is unknown or a variable it needs is missing.
    """
    env = environment() if env is None else env
    backend = _get(env, "EMAIL_BACKEND", "mailpit").lower()
    sender = _get(env, "SENDER_EMAIL")
    if not sender:
        raise ValueError("SENDER_EMAIL is not set; fill it in .env")
    sender_name = _get(env, "SENDER_NAME", "Monitorizare parc eolian")
    if backend == "mailpit":
        return SmtpSettings(
            backend=backend,
            host=_get(env, "MAILPIT_HOST", "127.0.0.1"),
            port=int(_get(env, "MAILPIT_SMTP_PORT", "1025")),
            starttls=False,
            sender=sender,
            sender_name=sender_name,
        )
    if backend == "gmail":
        password = _get(env, "GMAIL_APP_PASSWORD").replace(" ", "")
        if not password:
            raise ValueError("GMAIL_APP_PASSWORD is not set; fill it in .env")
        return SmtpSettings(
            backend=backend,
            host="smtp.gmail.com",
            port=587,
            starttls=True,
            sender=sender,
            sender_name=sender_name,
            username=sender,
            password=password,
        )
    raise ValueError("EMAIL_BACKEND must be mailpit or gmail")


@dataclass(frozen=True)
class TwilioSettings:
    """Twilio credentials and call options. The auth token never appears in `repr`."""

    account_sid: str
    caller_id: str
    voice: str
    language: str
    ring_timeout: int
    machine_detection_timeout: int
    auth_token: str = field(default="", repr=False)


def twilio_settings(env: Mapping[str, str] | None = None) -> TwilioSettings:
    """
    Twilio credentials, caller ID and call options.

    Optional variables: `TWILIO_VOICE` (default `Google.ro-RO-Wavenet-B`),
    `CALL_RING_TIMEOUT` seconds of ringing before no-answer (default 30) and
    `CALL_AMD_TIMEOUT` seconds for answering machine detection (default 10).

    :param env: Variables to read. Defaults to None, meaning `environment()`.

    :returns: The settings.
    :raises ValueError: When a required variable is missing.
    """
    env = environment() if env is None else env
    required = {
        name: _get(env, name)
        for name in ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "SENDER_PHONE"]
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"{', '.join(missing)} not set; fill in .env")
    return TwilioSettings(
        account_sid=required["TWILIO_ACCOUNT_SID"],
        auth_token=required["TWILIO_AUTH_TOKEN"],
        caller_id=required["SENDER_PHONE"].replace(" ", "").replace("-", ""),
        voice=_get(env, "TWILIO_VOICE", "Google.ro-RO-Wavenet-B"),
        language="ro-RO",
        ring_timeout=int(_get(env, "CALL_RING_TIMEOUT", "30")),
        machine_detection_timeout=int(_get(env, "CALL_AMD_TIMEOUT", "10")),
    )


def call_provider(env: Mapping[str, str] | None = None) -> str:
    """
    Which provider places calls: `CALL_PROVIDER`, `twilio` (default) or `infobip`.

    :param env: Variables to read. Defaults to None, meaning `environment()`.

    :returns: The provider name.
    :raises ValueError: When the value is not one of `CALL_PROVIDERS`.
    """
    provider = _get(env, "CALL_PROVIDER", "twilio").lower()
    if provider not in CALL_PROVIDERS:
        raise ValueError(f"CALL_PROVIDER must be one of {', '.join(CALL_PROVIDERS)}")
    return provider


@dataclass(frozen=True)
class InfobipSettings:
    """Infobip credentials and call options. The API key never appears in `repr`."""

    base_url: str
    voice: str
    language: str
    caller_id: str
    ring_timeout: int
    machine_detection: str
    api_key: str = field(default="", repr=False)


def infobip_settings(env: Mapping[str, str] | None = None) -> InfobipSettings:
    """
    Infobip credentials and call options.

    Optional variables: `INFOBIP_VOICE` (default `Carmen`, the free Romanian voice),
    `INFOBIP_FROM` caller ID (default empty: the trial's pre-registered sender),
    `INFOBIP_MACHINE_DETECTION` (`continue` or `hangup`; default empty, off, because Infobip
    enables it per account on request) and `CALL_RING_TIMEOUT` (default 30).

    :param env: Variables to read. Defaults to None, meaning `environment()`.

    :returns: The settings, with `base_url` as an `https://` URL without a trailing slash.
    :raises ValueError: When a required variable is missing or a value is invalid.
    """
    env = environment() if env is None else env
    required = {name: _get(env, name) for name in ["INFOBIP_API_KEY", "INFOBIP_BASE_URL"]}
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"{', '.join(missing)} not set; fill in .env")
    base_url = required["INFOBIP_BASE_URL"].rstrip("/")
    if not base_url.startswith("https://"):
        base_url = "https://" + base_url.removeprefix("http://")
    machine_detection = _get(env, "INFOBIP_MACHINE_DETECTION").lower()
    if machine_detection not in {"", "continue", "hangup"}:
        raise ValueError("INFOBIP_MACHINE_DETECTION must be empty, continue or hangup")
    return InfobipSettings(
        base_url=base_url,
        api_key=required["INFOBIP_API_KEY"],
        voice=_get(env, "INFOBIP_VOICE", "Carmen"),
        language="ro",
        caller_id=_get(env, "INFOBIP_FROM").replace(" ", "").replace("-", "").lstrip("+"),
        ring_timeout=int(_get(env, "CALL_RING_TIMEOUT", "30")),
        machine_detection=machine_detection,
    )
