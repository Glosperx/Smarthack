"""Tests for the on-call rotation and its `${VAR}` placeholders."""

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from alerting.oncall import ONCALL_FILE, load_oncall

FAKE_ENV = {"ONCALL_EMAIL": "garda@example.com", "ONCALL_PHONE": "+40700000001"}


def _write(tmp_path: Path, people: list[dict[str, str]]) -> Path:
    path = tmp_path / "oncall.json"
    path.write_text(json.dumps({"people": people}), encoding="utf-8")
    return path


def test_committed_rotation_has_one_person_from_env() -> None:
    rotation = load_oncall(ONCALL_FILE, env=FAKE_ENV)
    assert [(p.id, p.email, p.phone) for p in rotation.people] == [
        ("garda", FAKE_ENV["ONCALL_EMAIL"], FAKE_ENV["ONCALL_PHONE"])
    ]


def test_committed_rotation_holds_no_contact_details() -> None:
    text = ONCALL_FILE.read_text(encoding="utf-8")
    assert "@" not in text and "+40" not in text


@pytest.mark.parametrize("env", [{}, FAKE_ENV | {"ONCALL_EMAIL": "  "}])
def test_unset_or_empty_placeholder_names_the_variable(env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"\$\{ONCALL_EMAIL\} is not set"):
        load_oncall(ONCALL_FILE, env=env)


@pytest.mark.parametrize("phone", ["0712345678", "+40 712 345 678", "+4", "40712345678"])
def test_phone_must_be_e164_and_the_error_hides_it(tmp_path: Path, phone: str) -> None:
    path = _write(tmp_path, [{"id": "a", "name": "A", "email": "a@example.com", "phone": phone}])
    with pytest.raises(ValidationError) as error:
        load_oncall(path, env={})
    assert phone not in str(error.value)


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    person = {"id": "a", "name": "A", "email": "a@example.com", "phone": "+40700000001"}
    with pytest.raises(ValidationError, match="only once"):
        load_oncall(_write(tmp_path, [person, person]), env={})


def test_order_is_escalation_order(tmp_path: Path) -> None:
    people = [
        {"id": id_, "name": id_, "email": "a@example.com", "phone": "+40700000001"}
        for id_ in ["second-is-first", "first-is-second"]
    ]
    rotation = load_oncall(_write(tmp_path, people), env={})
    assert [person.id for person in rotation.people] == ["second-is-first", "first-is-second"]
