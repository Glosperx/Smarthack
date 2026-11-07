"""Tests for the alert and decision models and the four example cases."""

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import pytest

from alerting.models import Alert, Case, Decision, TurbineRisk, load_case

EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.json"))
BUCHAREST = ZoneInfo("Europe/Bucharest")


def _example(name: str) -> dict[str, Any]:
    path = next(path for path in EXAMPLES if path.name.startswith(name))
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_there_are_four_examples_that_all_load() -> None:
    assert len(EXAMPLES) == 4
    for path in EXAMPLES:
        load_case(path)


def test_examples_cover_two_email_only_and_two_with_call() -> None:
    channels = sorted(load_case(path).decision.channel for path in EXAMPLES)
    assert channels == ["doar_email", "doar_email", "email_si_apel", "email_si_apel"]


def test_one_call_example_is_on_friday_evening() -> None:
    friday_evening = [
        case
        for case in map(load_case, EXAMPLES)
        if case.decision.wants_call
        and case.alert.created_at.astimezone(BUCHAREST).weekday() == 4
        and case.alert.created_at.astimezone(BUCHAREST).hour >= 18
    ]
    assert len(friday_evening) == 1


def test_one_example_was_overridden_by_a_rule() -> None:
    rules = [load_case(path).decision.overridden_by_rule for path in EXAMPLES]
    assert sum(rule is not None for rule in rules) == 1


def test_examples_keep_romanian_diacritics() -> None:
    parks = {load_case(path).alert.park for path in EXAMPLES}
    assert {"Măgura Nord", "Câmpia Șoimilor", "Dealul Țarinii"} == parks


@pytest.mark.parametrize(("turbine_id", "number"), [("T07", 7), ("WTG3", 3), ("12", 12)])
def test_turbine_number_drops_prefix_and_leading_zeros(turbine_id: str, number: int) -> None:
    assert TurbineRisk(turbine_id=turbine_id, probability=0.5).number == number


@pytest.mark.parametrize("turbine_id", ["T00", "T", "", "T07a", "T-7"])
def test_turbine_id_without_a_number_is_refused(turbine_id: str) -> None:
    with pytest.raises(ValidationError):
        TurbineRisk(turbine_id=turbine_id, probability=0.5)


def test_turbines_by_risk_puts_the_most_likely_first() -> None:
    alert = load_case(EXAMPLES[1]).alert
    reordered = alert.model_copy(update={"turbines": list(reversed(alert.turbines))})
    assert [t.turbine_id for t in reordered.turbines_by_risk] == ["T02", "T05"]


@pytest.mark.parametrize(
    "change",
    [
        {"severity": "urgent"},
        {"channel": "sms"},
        {"confidence": 1.2},
        {"probabilities": {"medie": -0.1}},
        {"probabilities": {}},
        {"extra_field": 1},
    ],
)
def test_decision_refuses_values_outside_the_format(change: dict[str, Any]) -> None:
    data = _example("03")["decision"] | change
    with pytest.raises(ValidationError):
        Decision.model_validate(data)


def test_decision_requires_overridden_by_rule_even_when_null() -> None:
    data = _example("03")["decision"]
    del data["overridden_by_rule"]
    with pytest.raises(ValidationError, match="overridden_by_rule"):
        Decision.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"window_end": "2026-11-12T03:00:00+02:00"},
        {"created_at": "2026-11-11T14:05:00"},
        {"turbines": []},
        {"turbines": [{"turbine_id": "T07", "probability": 0.8}] * 2},
        {
            "turbines": [
                {"turbine_id": "T7", "probability": 0.8},
                {"turbine_id": "T07", "probability": 0.1},
            ]
        },
        {"hours_to_failure": -1},
        {"estimated_loss_ron": -5},
    ],
)
def test_alert_refuses_inconsistent_values(change: dict[str, Any]) -> None:
    data = _example("03")["alert"] | change
    with pytest.raises(ValidationError):
        Alert.model_validate(data)


def test_case_refuses_a_decision_for_another_alert() -> None:
    data = _example("03")
    data["decision"]["alert_id"] = "ALR-other"
    with pytest.raises(ValidationError, match="ALR-other"):
        Case.model_validate(data)


def test_models_are_immutable() -> None:
    case = load_case(EXAMPLES[0])
    with pytest.raises(ValidationError):
        case.decision.channel = "email_si_apel"  # type: ignore[misc]


def test_friday_example_is_really_a_friday() -> None:
    created = load_case(EXAMPLES[3]).alert.created_at
    assert created == datetime(2026, 11, 13, 21, 40, tzinfo=BUCHAREST)
