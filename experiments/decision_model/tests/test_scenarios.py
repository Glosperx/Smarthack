from collections import Counter

import pytest

from decision_model.scenarios import all_scenarios, channel_scenarios, load_border_labels


def test_about_eighty_scenarios_per_decision_with_unique_ids() -> None:
    scenarios = all_scenarios()
    counts = Counter(s.decision for s in scenarios)

    assert 75 <= counts["ml2"] <= 85
    assert 75 <= counts["channel"] <= 85
    assert len({s.id for s in scenarios}) == len(scenarios)


def test_clear_cases_follow_the_rule_and_cover_every_option() -> None:
    scenarios = all_scenarios()
    clear = [s for s in scenarios if s.kind == "clar"]

    assert all(s.label == s.rule for s in clear)
    assert {s.label for s in clear if s.decision == "ml2"} == {"da", "nu"}
    assert {s.label for s in clear if s.decision == "channel"} == {
        "doar_email",
        "email_si_apel",
        "nimic",
    }


def test_every_border_case_has_a_label_with_a_reason() -> None:
    labels = load_border_labels()
    border = [s for s in all_scenarios() if s.kind == "granita"]

    assert {s.id for s in border} == set(labels)
    assert all(s.rationale for s in border)


def test_hard_rule_holds_in_the_labels() -> None:
    for s in channel_scenarios():
        if str(s.state["health_status"]).upper() == "CRITICAL":
            assert s.label == "email_si_apel", s.id


def test_missing_border_label_is_an_error() -> None:
    with pytest.raises(KeyError, match="no label"):
        channel_scenarios(labels={})
