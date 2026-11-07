"""Tests for the environment accessors and the recipient allowlist."""

import pytest

from alerting.allowlist import Allowlist, RecipientNotAllowed, mask_email, mask_phone
from alerting.config import dry_run, smtp_settings


@pytest.mark.parametrize("env", [{}, {"DRY_RUN": ""}, {"DRY_RUN": "true"}, {"DRY_RUN": "1"}])
def test_dry_run_is_on_unless_explicitly_off(env: dict[str, str]) -> None:
    assert dry_run(env) is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "nu"])
def test_dry_run_turns_off_only_with_a_false_value(value: str) -> None:
    assert dry_run({"DRY_RUN": value}) is False


def test_dry_run_refuses_a_value_it_cannot_read() -> None:
    with pytest.raises(ValueError, match="DRY_RUN"):
        dry_run({"DRY_RUN": "maybe"})


def test_mailpit_is_the_default_backend() -> None:
    settings = smtp_settings({"SENDER_EMAIL": "alerts@example.com"})
    assert (settings.backend, settings.host, settings.port) == ("mailpit", "127.0.0.1", 1025)
    assert not settings.starttls and not settings.username


def test_gmail_needs_an_app_password_and_hides_it() -> None:
    env = {"EMAIL_BACKEND": "gmail", "SENDER_EMAIL": "alerts@gmail.com"}
    with pytest.raises(ValueError, match="GMAIL_APP_PASSWORD"):
        smtp_settings(env)
    settings = smtp_settings(env | {"GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop"})
    assert settings.password == "abcdefghijklmnop"
    assert "abcdefghijklmnop" not in repr(settings)
    assert (settings.host, settings.port, settings.starttls) == ("smtp.gmail.com", 587, True)


def test_unknown_backend_and_missing_sender_are_refused() -> None:
    with pytest.raises(ValueError, match="EMAIL_BACKEND"):
        smtp_settings({"EMAIL_BACKEND": "sendgrid", "SENDER_EMAIL": "a@example.com"})
    with pytest.raises(ValueError, match="SENDER_EMAIL"):
        smtp_settings({})


def test_empty_allowlist_refuses_everyone() -> None:
    allowlist = Allowlist.from_env({})
    with pytest.raises(RecipientNotAllowed):
        allowlist.check_email("anyone@example.com")
    with pytest.raises(RecipientNotAllowed):
        allowlist.check_phone("+40700000001")


def test_allowlist_ignores_case_and_spacing() -> None:
    allowlist = Allowlist.from_env(
        {
            "ALLOWED_EMAILS": " Garda@Example.com , b@example.com",
            "ALLOWED_PHONES": "+40 700-000 001",
        }
    )
    assert allowlist.check_email("garda@example.COM") == "garda@example.COM"
    assert allowlist.check_phone("+40700000001") == "+40700000001"


def test_refusal_message_masks_the_contact() -> None:
    allowlist = Allowlist.from_env({})
    with pytest.raises(RecipientNotAllowed) as error:
        allowlist.check_email("secret.person@example.com")
    assert "secret.person" not in str(error.value)
    with pytest.raises(RecipientNotAllowed) as error:
        allowlist.check_phone("+40712345678")
    assert "12345" not in str(error.value)


def test_masks() -> None:
    assert mask_email("someone@example.com") == "so***@example.com"
    assert mask_phone("+40712345678") == "+407******78"
