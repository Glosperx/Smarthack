"""Tests for deterministic escalation, driven by simulated call outcomes."""

from pathlib import Path

import pytest

from alerting.escalation import escalate, retries_per_person, retry_delay_minutes
from alerting.oncall import OnCallPerson
from alerting.simulation import SimulatedProvider, parse_outcomes
from alerting.state import MAX_CALLS_PER_ALERT, StateStore

FIRST = OnCallPerson(id="garda-1", name="Gardă 1", email="g1@example.com", phone="+40700000001")
SECOND = OnCallPerson(id="garda-2", name="Gardă 2", email="g2@example.com", phone="+40700000002")
ENV = {
    "ALLOWED_PHONES": "+40700000001,+40700000002",
    "DRY_RUN": "false",
    "ESCALATION_RETRY_MINUTES": "2",
}


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "alerts.json")


def _run(
    script: str,
    store: StateStore,
    people: list[OnCallPerson] | None = None,
    env: dict[str, str] = ENV,
) -> tuple[list[tuple[str, int, str]], str, list[float], SimulatedProvider]:
    provider = SimulatedProvider(parse_outcomes(script))
    sleeps: list[float] = []
    outcome = escalate(
        "A1",
        "text",
        people or [FIRST, SECOND],
        env=env,
        provider=provider,
        store=store,
        sleep=sleeps.append,
    )
    calls = [(a.person, a.try_number, a.result.status) for a in outcome.attempts]
    return calls, outcome.stopped, sleeps, provider


def test_answer_on_the_first_call_stops_at_once(store: StateStore) -> None:
    calls, stopped, sleeps, _ = _run("completed:human", store)
    assert calls == [("garda-1", 1, "completed")]
    assert stopped == "answered" and sleeps == []


@pytest.mark.parametrize(
    "first", ["no-answer", "busy", "completed:machine_start", "completed:unknown", "failed"]
)
def test_not_answered_means_one_retry_after_the_delay(store: StateStore, first: str) -> None:
    calls, stopped, sleeps, _ = _run(f"{first},completed:human", store)
    assert [(person, try_number) for person, try_number, _ in calls] == [
        ("garda-1", 1),
        ("garda-1", 2),
    ]
    assert stopped == "answered" and sleeps == [120.0]


def test_two_misses_move_on_to_the_next_person_without_waiting(store: StateStore) -> None:
    calls, stopped, sleeps, provider = _run("no-answer,busy,completed:human", store)
    assert calls == [
        ("garda-1", 1, "no-answer"),
        ("garda-1", 2, "busy"),
        ("garda-2", 1, "completed"),
    ]
    assert stopped == "answered" and sleeps == [120.0]
    assert [to for to, _ in provider.calls] == ["+40700000001", "+40700000001", "+40700000002"]


def test_nobody_answers_ends_at_the_per_alert_cap(store: StateStore) -> None:
    calls, stopped, _, _ = _run("no-answer,no-answer,no-answer,no-answer", store)
    assert len(calls) == MAX_CALLS_PER_ALERT + 1
    assert calls[-1] == ("garda-2", 2, "limit_reached")
    assert stopped == "limit_reached"
    assert store.calls_made("A1") == MAX_CALLS_PER_ALERT


def test_single_person_is_tried_twice_then_exhausted(store: StateStore) -> None:
    calls, stopped, sleeps, _ = _run("no-answer,completed:machine_start", store, [FIRST])
    assert calls == [("garda-1", 1, "no-answer"), ("garda-1", 2, "completed")]
    assert stopped == "exhausted" and sleeps == [120.0]


def test_zero_retries_means_one_call_per_person(store: StateStore) -> None:
    env = ENV | {"CALL_RETRIES_PER_PERSON": "0"}
    calls, stopped, sleeps, _ = _run("no-answer,no-answer", store, [FIRST, SECOND], env)
    assert calls == [("garda-1", 1, "no-answer"), ("garda-2", 1, "no-answer")]
    assert stopped == "exhausted" and sleeps == []


def test_person_outside_the_allowlist_is_skipped_without_retry(store: StateStore) -> None:
    env = ENV | {"ALLOWED_PHONES": "+40700000002"}
    calls, stopped, sleeps, provider = _run("completed:human", store, env=env)
    assert calls == [("garda-1", 1, "refused"), ("garda-2", 1, "completed")]
    assert stopped == "answered" and sleeps == []
    assert len(provider.calls) == 1


def test_dry_run_shows_the_first_call_only(store: StateStore) -> None:
    env = ENV | {"DRY_RUN": "true"}
    calls, stopped, sleeps, provider = _run("completed:human", store, env=env)
    assert calls == [("garda-1", 1, "dry_run")]
    assert stopped == "dry_run" and sleeps == [] and provider.calls == []


def test_same_script_same_calls(store: StateStore, tmp_path: Path) -> None:
    first, _, _, _ = _run("busy,no-answer,completed:human", store)
    second, _, _, _ = _run("busy,no-answer,completed:human", StateStore(tmp_path / "other.json"))
    assert first == second


def test_retry_delay_setting() -> None:
    assert retry_delay_minutes({}) == 5
    assert retry_delay_minutes({"ESCALATION_RETRY_MINUTES": "0.5"}) == 0.5
    with pytest.raises(ValueError):
        retry_delay_minutes({"ESCALATION_RETRY_MINUTES": "-1"})


def test_unknown_simulated_status_is_refused() -> None:
    with pytest.raises(ValueError, match="ringing"):
        parse_outcomes("ringing")


def test_retries_per_person_default_and_validation() -> None:
    """One retry unless configured; 0 means one call only; a negative number is refused."""
    assert retries_per_person({}) == 1
    assert retries_per_person({"CALL_RETRIES_PER_PERSON": "0"}) == 0
    with pytest.raises(ValueError):
        retries_per_person({"CALL_RETRIES_PER_PERSON": "-1"})
