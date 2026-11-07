"""Tests for dispatch(): email always, call when asked, once per alert, LangGraph-ready."""

from email.message import EmailMessage
import json
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from pydantic import ValidationError
import pytest

from alerting import mailer
from alerting.dispatch import dispatch, langgraph_node
from alerting.models import Case, load_case
from alerting.oncall import OnCallPerson
from alerting.simulation import SimulatedProvider, parse_outcomes
from alerting.state import StateStore

EXAMPLES = Path(__file__).parent.parent / "examples"
PEOPLE = [
    OnCallPerson(id="garda-1", name="G1", email="garda1@example.com", phone="+40700000001"),
    OnCallPerson(id="garda-2", name="G2", email="garda2@example.com", phone="+40700000002"),
]
LIVE = {
    "SENDER_EMAIL": "alerts@example.com",
    "ALLOWED_EMAILS": "garda1@example.com,garda2@example.com",
    "ALLOWED_PHONES": "+40700000001,+40700000002",
    "DRY_RUN": "false",
    "ESCALATION_RETRY_MINUTES": "1",
}


class FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        pass

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


@pytest.fixture(autouse=True)
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "alerts.json")


def _case(prefix: str) -> Case:
    return load_case(next(EXAMPLES.glob(f"{prefix}*.json")))


def _dispatch(
    case: Case,
    store: StateStore,
    script: str = "completed:human",
    env: dict[str, str] = LIVE,
) -> tuple[dict[str, Any], SimulatedProvider, list[float]]:
    provider = SimulatedProvider(parse_outcomes(script))
    sleeps: list[float] = []
    summary = dispatch(
        case.alert,
        case.decision,
        env=env,
        people=PEOPLE,
        provider=provider,
        store=store,
        sleep=sleeps.append,
    )
    return summary, provider, sleeps


def test_email_only_decision_sends_email_and_no_call(store: StateStore) -> None:
    summary, provider, _ = _dispatch(_case("01"), store)
    assert summary["status"] == "dispatched"
    assert [e["status"] for e in summary["email"]] == ["sent", "sent"]
    assert summary["call"] == {"requested": False}
    assert provider.calls == []


def test_call_decision_sends_email_then_escalates(store: StateStore, smtp: type[FakeSMTP]) -> None:
    summary, provider, sleeps = _dispatch(_case("04"), store, "no-answer,busy,completed:human")
    assert len(smtp.sent) == 2
    call = summary["call"]
    assert call["requested"] and call["answered"] and call["answered_by_person"] == "garda-2"
    assert [(a["person"], a["try"], a["status"]) for a in call["attempts"]] == [
        ("garda-1", 1, "no-answer"),
        ("garda-1", 2, "busy"),
        ("garda-2", 1, "completed"),
    ]
    assert sleeps == [60.0]
    assert "Turbinele unsprezece și doisprezece" in provider.calls[0][1]


def test_the_same_alert_is_never_dispatched_twice(store: StateStore, smtp: type[FakeSMTP]) -> None:
    case = _case("03")
    first, _, _ = _dispatch(case, store)
    second, provider, _ = _dispatch(case, store)
    assert first["status"] == "dispatched" and second["status"] == "duplicate"
    assert second["previous_summary"]["status"] == "dispatched"
    assert len(smtp.sent) == 2 and provider.calls == []


def test_dry_run_sends_nothing_and_can_be_repeated(store: StateStore, smtp: type[FakeSMTP]) -> None:
    env = LIVE | {"DRY_RUN": "true"}
    case = _case("04")
    first, provider, _ = _dispatch(case, store, env=env)
    second, _, _ = _dispatch(case, store, env=env)
    assert first["status"] == second["status"] == "dry_run"
    assert [e["status"] for e in first["email"]] == ["dry_run", "dry_run"]
    assert first["call"]["stopped"] == "dry_run"
    assert smtp.sent == [] and provider.calls == []
    assert not store.is_dispatched(case.alert.alert_id)


def test_a_crash_midway_still_blocks_a_second_dispatch(
    store: StateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case("04")

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("provider down")

    monkeypatch.setattr("alerting.dispatch.escalate", explode)
    with pytest.raises(RuntimeError):
        _dispatch(case, store)
    again, _, _ = _dispatch(case, store)
    assert again["status"] == "duplicate"
    assert again["previous_summary"] == {"status": "in_progress"}


def test_decision_for_another_alert_is_refused(store: StateStore) -> None:
    case = _case("03")
    other = case.decision.model_copy(update={"alert_id": "ALR-other"})
    with pytest.raises(ValidationError, match="ALR-other"):
        dispatch(case.alert, other, env=LIVE, people=PEOPLE, store=store)


def test_plain_dicts_from_graph_state_are_accepted(store: StateStore) -> None:
    data = json.loads(next(EXAMPLES.glob("03*.json")).read_text(encoding="utf-8"))
    summary = dispatch(
        data["alert"],
        data["decision"],
        env=LIVE,
        people=PEOPLE,
        provider=SimulatedProvider(parse_outcomes("completed:human")),
        store=store,
    )
    assert summary["status"] == "dispatched" and summary["call"]["answered"]


def test_summary_is_json_and_masks_contacts(store: StateStore) -> None:
    summary, _, _ = _dispatch(_case("04"), store, "no-answer,completed:human")
    text = json.dumps(summary, ensure_ascii=False)
    for contact in ["garda1@example.com", "garda2@example.com", "+40700000001", "+40700000002"]:
        assert contact not in text
    assert summary["overridden_by_rule"].startswith("R4")


def test_langgraph_node_reads_state_and_writes_the_summary(
    store: StateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case("01")
    calls: list[tuple[Any, Any]] = []

    def fake_dispatch(alert: Any, decision: Any) -> dict[str, Any]:
        calls.append((alert, decision))
        return {"status": "dispatched"}

    monkeypatch.setattr("alerting.dispatch.dispatch", fake_dispatch)
    node = langgraph_node()
    update = node({"alert": case.alert, "decision": case.decision, "other": 1})
    assert update == {"dispatch": {"status": "dispatched"}}
    assert calls == [(case.alert, case.decision)]
