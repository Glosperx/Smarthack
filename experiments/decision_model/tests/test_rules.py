import pytest

from decision_model.rules import failure_day, overlapping_failures, rule_channel, rule_ml2


def _t(tid: int, days: float, status: str = "WARNING", park: str = "p") -> dict[str, object]:
    return {"turbine_id": tid, "park_id": park, "health_status": status, "days_to_failure": days}


@pytest.mark.parametrize(("days", "day"), [(0.8, 0), (1.0, 1), (2.99, 2), (-0.5, 0), (8.0, 8)])
def test_failure_day_rounds_down_and_never_goes_negative(days: float, day: int) -> None:
    assert failure_day(days) == day


def test_overlap_uses_neighbours_in_time() -> None:
    assert overlapping_failures({1: 0, 2: 1, 3: 5}, 1) == {1, 2}
    assert overlapping_failures({1: 0, 2: 2, 3: 4}, 1) == set()
    assert overlapping_failures({1: 3}, 1) == set()


def test_rule_ml2_keeps_only_own_park_turbines_that_need_repair() -> None:
    assert rule_ml2("p", [_t(1, 1.2), _t(2, 1.8)], 1) == "da"
    assert rule_ml2("p", [_t(1, 1.2), _t(2, 1.8, park="q")], 1) == "nu"
    assert rule_ml2("p", [_t(1, 1.2), _t(2, 1.8, "WATCH")], 1) == "nu"
    assert rule_ml2("p", [_t(1, 1.2, "critical"), _t(2, 1.8)], 1) == "da"
    assert rule_ml2("p", [_t(1, 1.2), _t(2, 3.5)], 1) == "nu"


def test_rule_ml2_treats_no_failure_value_as_a_day() -> None:
    assert rule_ml2("p", [_t(1, 8.0), _t(2, 8.0)], 1) == "da"


@pytest.mark.parametrize(
    ("status", "days", "probability", "channel"),
    [
        ("CRITICAL", 7.0, 0.0, "email_si_apel"),
        ("critical", 7.0, 0.0, "email_si_apel"),
        ("NORMAL", 2.0, 0.0, "email_si_apel"),
        ("NORMAL", 2.01, 0.69, "doar_email"),
        ("NORMAL", 5.0, 0.70, "email_si_apel"),
        ("WATCH", 5.0, 0.0, "doar_email"),
        ("WARNING", 8.0, 0.0, "doar_email"),
        ("NORMAL", 8.0, 0.30, "doar_email"),
        ("NORMAL", 8.0, 0.29, "nimic"),
        ("UNKNOWN", 8.0, 0.1, "nimic"),
    ],
)
def test_rule_channel_matches_classify_alert_channel(
    status: str, days: float, probability: float, channel: str
) -> None:
    assert rule_channel(status, days, probability) == channel
