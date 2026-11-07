"""Tests for the alert email: rendering, the allowlist and dry-run gates, and SMTP."""

from email.message import EmailMessage
import json
from pathlib import Path
from types import TracebackType
from typing import Any, Self
import urllib.error
import urllib.request

import pytest

from alerting import mailer
from alerting.mailer import render_email, send_alert_email
from alerting.models import Case, load_case

EXAMPLES = Path(__file__).parent.parent / "examples"
ALLOWED = "garda1@example.com,garda2@example.com"
BASE_ENV = {"SENDER_EMAIL": "alerts@example.com", "ALLOWED_EMAILS": ALLOWED}


def _case(prefix: str) -> Case:
    return load_case(next(EXAMPLES.glob(f"{prefix}*.json")))


class FakeSMTP:
    """Records what would have been sent instead of opening a connection."""

    sent: list[EmailMessage] = []
    instances = 0

    def __init__(self, host: str, port: int, timeout: float) -> None:
        FakeSMTP.instances += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        FakeSMTP.sent.append(message)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.sent = []
    FakeSMTP.instances = 0
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_subject_matches_the_agreed_format() -> None:
    case = _case("03")
    assert render_email(case.alert, case.decision).subject == (
        "[RIDICAT] Parc Dealul Țarinii – turbina 7: defecțiune probabilă în ~18h"
    )


def test_lead_sentence_names_the_turbine_risk_and_time() -> None:
    case = _case("03")
    text = render_email(case.alert, case.decision).text
    assert "Turbina 7 are risc ridicat de defecțiune în aproximativ 18 ore." in text
    assert "Pierdere estimată: 145.000 de lei" in text


@pytest.mark.parametrize("prefix", ["01", "02", "03", "04"])
def test_rule_override_is_mentioned_only_when_there_is_one(prefix: str) -> None:
    case = _case(prefix)
    rendered = render_email(case.alert, case.decision)
    mentioned = "schimbată de o regulă" in rendered.text
    assert mentioned == (case.decision.overridden_by_rule is not None)
    assert mentioned == ("schimbată de o regulă" in rendered.html)


@pytest.mark.parametrize("prefix", ["01", "02", "03", "04"])
def test_call_is_announced_only_with_email_si_apel(prefix: str) -> None:
    case = _case(prefix)
    text = render_email(case.alert, case.decision).text
    assert ("sunată și pe telefon" in text) == case.decision.wants_call


def test_html_escapes_values_coming_from_the_alert() -> None:
    case = _case("03")
    alert = case.alert.model_copy(update={"park": "<script>x</script>"})
    html = render_email(alert, case.decision).html
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


def test_dry_run_is_the_default_and_opens_no_connection(smtp: type[FakeSMTP]) -> None:
    case = _case("03")
    results = send_alert_email(case.alert, case.decision, ["garda1@example.com"], env=BASE_ENV)
    assert [result.status for result in results] == ["dry_run"]
    assert smtp.instances == 0


def test_recipient_outside_the_allowlist_is_refused_even_when_sending(
    smtp: type[FakeSMTP],
) -> None:
    case = _case("03")
    env = BASE_ENV | {"DRY_RUN": "false"}
    results = send_alert_email(
        case.alert, case.decision, ["intruder@example.com", "garda1@example.com"], env=env
    )
    assert [(r.recipient, r.status) for r in results] == [
        ("in***@example.com", "refused"),
        ("ga***@example.com", "sent"),
    ]
    assert [message["To"] for message in smtp.sent] == ["garda1@example.com"]


def test_duplicate_recipients_get_one_email(smtp: type[FakeSMTP]) -> None:
    case = _case("03")
    env = BASE_ENV | {"DRY_RUN": "false"}
    recipients = ["garda1@example.com", "GARDA1@example.com ", "garda2@example.com"]
    results = send_alert_email(case.alert, case.decision, recipients, env=env)
    assert len(results) == 2 and len(smtp.sent) == 2


def test_message_is_text_then_html_with_headers(smtp: type[FakeSMTP]) -> None:
    case = _case("04")
    send_alert_email(
        case.alert, case.decision, ["garda1@example.com"], env=BASE_ENV | {"DRY_RUN": "false"}
    )
    message = smtp.sent[0]
    assert message["X-Alert-Id"] == "ALR-2026-11-13-0004"
    assert message["Subject"].startswith("[CRITIC] Parc Măgura Nord")
    parts = [part.get_content_type() for part in message.iter_parts()]
    assert parts == ["text/plain", "text/html"]


def test_connection_failure_is_reported_per_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ConnectionRefusedError("nobody listening")

    monkeypatch.setattr(mailer.smtplib, "SMTP", refuse)
    case = _case("03")
    env = BASE_ENV | {"DRY_RUN": "false"}
    results = send_alert_email(
        case.alert, case.decision, ["garda1@example.com", "garda2@example.com"], env=env
    )
    assert [r.status for r in results] == ["failed", "failed"]
    assert "ConnectionRefusedError" in results[0].detail


def _mailpit(path: str, method: str = "GET") -> Any:
    request = urllib.request.Request(f"http://127.0.0.1:8025{path}", method=method)
    with urllib.request.urlopen(request, timeout=2) as response:
        body = response.read()
    return json.loads(body) if body.startswith(b"{") else body


def _mailpit_running() -> bool:
    try:
        _mailpit("/api/v1/info")
    except (urllib.error.URLError, OSError):
        return False
    return True


@pytest.mark.mailpit
@pytest.mark.skipif(not _mailpit_running(), reason="Mailpit is not running: docker compose up -d")
def test_email_arrives_in_mailpit_with_diacritics_intact() -> None:
    case = _case("04")
    env = BASE_ENV | {"DRY_RUN": "false", "EMAIL_BACKEND": "mailpit"}
    _mailpit("/api/v1/messages", method="DELETE")
    results = send_alert_email(case.alert, case.decision, ["garda1@example.com"], env=env)
    assert [r.status for r in results] == ["sent"]

    summary = _mailpit("/api/v1/messages?limit=1")["messages"][0]
    message = _mailpit(f"/api/v1/message/{summary['ID']}")
    expected = render_email(case.alert, case.decision)
    assert message["Subject"] == expected.subject
    # SMTP carries CRLF line endings; the words must arrive unchanged.
    assert message["Text"].replace("\r\n", "\n").strip() == expected.text.strip()
    assert "Decizia modelului a fost schimbată de o regulă." in message["HTML"]
    for word in ["Măgura", "critică", "defecțiune", "până", "și", "ATENȚIE"]:
        assert word in message["Text"]
