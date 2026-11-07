"""
# Alert email

Builds the alert email (plain text and HTML, from templates) and sends it, one message per
recipient, through the SMTP server `EMAIL_BACKEND` selects: Mailpit locally, or Gmail.

Three gates run before anything is sent, in this order:
1. every recipient is checked against `ALLOWED_EMAILS`; a refused one is reported, not sent;
2. with `DRY_RUN` (the default) the email is only logged;
3. otherwise it goes out over SMTP, and a failure is reported per recipient.

There is deliberately no argument that turns dry-run off: only the environment can.

The following can be imported from this module:
- `EmailResult`
- `RenderedEmail`
- `build_message`
- `email_context`
- `render_email`
- `send_alert_email`
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import logging
import smtplib
import ssl
from typing import Any, Literal

from alerting import config
from alerting.allowlist import Allowlist, RecipientNotAllowed, mask_email
from alerting.models import Alert, Decision
from alerting.templates import render
from alerting.wording import (
    SEVERITY,
    count,
    eta_long,
    eta_short,
    format_datetime,
    format_window,
    percent,
    turbines_phrase,
)

__all__ = [
    "EmailResult",
    "RenderedEmail",
    "build_message",
    "email_context",
    "render_email",
    "send_alert_email",
]

logger = logging.getLogger(__name__)

EmailStatus = Literal["sent", "dry_run", "refused", "failed"]

_CHANNEL_LABEL = {"doar_email": "doar email", "email_si_apel": "email și apel telefonic"}


@dataclass(frozen=True)
class RenderedEmail:
    """The three rendered parts of an alert email."""

    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class EmailResult:
    """What happened to the email for one recipient. `recipient` is masked."""

    recipient: str
    status: EmailStatus
    subject: str
    detail: str = ""


def _option_label(option: str) -> str:
    return SEVERITY[option].adjective if option in SEVERITY else option


def email_context(alert: Alert, decision: Decision) -> dict[str, Any]:
    """
    Prepare the values the email templates use.

    :param alert: The alert.
    :param decision: The decision made for it.

    :returns: The template variables.
    """
    turbines = alert.turbines_by_risk
    options = sorted(decision.probabilities.items(), key=lambda item: item[1], reverse=True)
    top_option, top_probability = options[0]
    return {
        "severity": SEVERITY[decision.severity],
        "park": alert.park,
        "turbines": [
            {"number": t.number, "id": t.turbine_id, "probability": percent(t.probability)}
            for t in turbines
        ],
        "turbines_phrase": turbines_phrase([t.number for t in turbines]),
        "eta_short": eta_short(alert.hours_to_failure),
        "eta_long": eta_long(alert.hours_to_failure),
        "window": format_window(alert.window_start, alert.window_end),
        "loss": count(alert.estimated_loss_ron, "leu", "lei"),
        "call": decision.wants_call,
        "channel_label": _CHANNEL_LABEL[decision.channel],
        "confidence": percent(decision.confidence),
        "probabilities": [
            {"label": _option_label(option), "value": percent(value)} for option, value in options
        ],
        "rule": decision.overridden_by_rule,
        "model_choice": f"{_option_label(top_option)} ({percent(top_probability)})",
        "alert_id": alert.alert_id,
        "created_at": format_datetime(alert.created_at),
    }


def render_email(alert: Alert, decision: Decision) -> RenderedEmail:
    """
    Render the subject, the plain-text body and the HTML body.

    :param alert: The alert.
    :param decision: The decision made for it.

    :returns: The rendered email.
    """
    context = email_context(alert, decision)
    subject = render("email_subject.txt.j2", **context)
    return RenderedEmail(
        subject=subject,
        text=render("email.txt.j2", **context),
        html=render("email.html.j2", subject=subject, **context),
    )


def build_message(
    rendered: RenderedEmail, settings: config.SmtpSettings, recipient: str, alert_id: str
) -> EmailMessage:
    """
    Assemble a multipart/alternative message, text first and HTML second.

    :param rendered: The rendered email.
    :param settings: Supplies the sender.
    :param recipient: The one address the message is for.
    :param alert_id: Copied into an `X-Alert-Id` header.

    :returns: The message, ready for `smtplib`.
    """
    message = EmailMessage()
    message["Subject"] = rendered.subject
    message["From"] = Address(display_name=settings.sender_name, addr_spec=settings.sender)
    message["To"] = recipient
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=settings.sender.partition("@")[2] or None)
    message["X-Alert-Id"] = alert_id
    message["Content-Language"] = "ro"
    message.set_content(rendered.text, charset="utf-8")
    message.add_alternative(rendered.html, subtype="html", charset="utf-8")
    return message


def _error(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _send(settings: config.SmtpSettings, messages: list[EmailMessage]) -> list[str | None]:
    """Send over one connection; return None per sent message, else the error."""
    try:
        with smtplib.SMTP(settings.host, settings.port, timeout=15) as smtp:
            if settings.starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.username:
                smtp.login(settings.username, settings.password)
            outcomes: list[str | None] = []
            for message in messages:
                try:
                    smtp.send_message(message)
                    outcomes.append(None)
                except smtplib.SMTPException as error:
                    outcomes.append(_error(error))
            return outcomes
    except (smtplib.SMTPException, OSError) as error:
        return [_error(error)] * len(messages)


def send_alert_email(
    alert: Alert,
    decision: Decision,
    recipients: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> list[EmailResult]:
    """
    Email the alert to each recipient, subject to the allowlist and `DRY_RUN`.

    :param alert: The alert.
    :param decision: The decision made for it.
    :param recipients: Addresses; duplicates (ignoring case) are emailed once.
    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.

    :returns: One result per distinct recipient, in input order.
    :raises ValueError: When the SMTP settings are incomplete.
    """
    env = config.environment() if env is None else env
    allowlist = Allowlist.from_env(env)
    settings = config.smtp_settings(env)
    rendered = render_email(alert, decision)

    distinct = list(dict.fromkeys(r.strip().lower() for r in recipients))
    results: dict[str, EmailResult] = {}
    to_send: dict[str, EmailMessage] = {}
    for recipient in distinct:
        try:
            allowlist.check_email(recipient)
        except RecipientNotAllowed as refusal:
            logger.warning("email refused: %s", refusal)
            results[recipient] = EmailResult(
                mask_email(recipient), "refused", rendered.subject, str(refusal)
            )
            continue
        to_send[recipient] = build_message(rendered, settings, recipient, alert.alert_id)

    if config.dry_run(env):
        for recipient in to_send:
            logger.info(
                "DRY_RUN: email to %s (not sent)\nSubject: %s\n\n%s",
                mask_email(recipient),
                rendered.subject,
                rendered.text,
            )
            results[recipient] = EmailResult(mask_email(recipient), "dry_run", rendered.subject)
    elif to_send:
        outcomes = _send(settings, list(to_send.values()))
        for recipient, failure in zip(to_send, outcomes, strict=True):
            masked = mask_email(recipient)
            if failure is None:
                logger.info("email sent via %s to %s", settings.backend, masked)
                results[recipient] = EmailResult(masked, "sent", rendered.subject, settings.backend)
            else:
                logger.error("email to %s failed via %s: %s", masked, settings.backend, failure)
                results[recipient] = EmailResult(masked, "failed", rendered.subject, failure)
    return [results[recipient] for recipient in distinct]
