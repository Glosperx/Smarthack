"""
# Unit tests for the decision model requests

The question texts are the ones the model was tested with, so they are pinned word for word. The
plan options are named and shuffled the same way every time, and the states carry what the tests
carried.
"""

from typing import Any

from smarthack.schemas.dispatch import AlertChannel
from smarthack.services.agent.decision_requests import (
    CHANNEL_OPTIONS,
    CHANNEL_POLICY,
    CHANNEL_QUESTION,
    PLAN_INSTRUCTIONS,
    build_channel_request,
    build_plan_request,
)
from smarthack.services.agent.repair_plans import build_requests, candidate_plans
from smarthack.services.agent.repair_scheduler import fill_wind

WIND = [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0]

#: The channel question with its policy, as written in `experiments/decision_model`.
TESTED_CHANNEL_TEXT = (
    "How should the maintenance crew be alerted about this turbine? days_to_failure is ML1's "
    "predicted number of days until the turbine fails (8 means no failure is predicted within the "
    "7-day horizon); fault_probability is ML1's probability that the turbine fails within 7 days. "
    "health_status is the condition assessment (NORMAL, WATCH, WARNING, CRITICAL). Policy: email "
    "and phone call when health_status is CRITICAL, or days_to_failure is at most 2, or "
    "fault_probability is at least 0.70. Otherwise email only when health_status is WARNING or "
    "WATCH, or fault_probability is at least 0.30. Otherwise no alert."
)


def _turbines() -> list[dict[str, Any]]:
    """
    Two failing turbines with an output estimate each.

    :returns turbines: Triage items as the graph holds them after the power model.
    """
    return [
        {
            "turbine_id": 1,
            "health_status": "WARNING",
            "days_to_failure": 4.0,
            "fault_probability": 0.512,
            "projected_mwh_7d": 10.04,
        },
        {
            "turbine_id": 2,
            "health_status": "CRITICAL",
            "days_to_failure": 4.5,
            "fault_probability": 0.9,
            "projected_mwh_7d": 40.0,
        },
    ]


def test_the_channel_question_is_the_tested_text_with_the_policy_from_the_constants() -> None:
    """Built from the thresholds the rule reads, the text is still the one that was tested."""
    assert CHANNEL_QUESTION + CHANNEL_POLICY == TESTED_CHANNEL_TEXT


def test_the_plan_question_is_the_tested_text() -> None:
    """The instructions of the plan question, word for word."""
    assert PLAN_INSTRUCTIONS == (
        "One maintenance crew serves this park and repairs at most one turbine per day. The "
        "options are complete repair plans, worked out from the forecast. Choose the plan that "
        "saves the most turbines; if several save the same number, choose the one with the "
        "smallest output lost on repair days. Which plan should the crew follow?"
    )


def test_the_channel_options_are_the_channel_values_in_the_tested_order() -> None:
    """The model answers with the same keys the schema stores."""
    assert list(CHANNEL_OPTIONS) == ["doar_email", "email_si_apel", "nimic"]
    assert set(CHANNEL_OPTIONS) == {channel.value for channel in AlertChannel}


def test_a_channel_request_carries_the_turbine_and_the_policy() -> None:
    """The state has the fields the test set had; the question has the policy."""
    item = {**_turbines()[0], "suspected_failure": "Gearbox Wear", "park_id": "ignored"}

    request = build_channel_request("wind_farm_a", item)

    assert request.state == {
        "park_id": "wind_farm_a",
        "turbine_id": 1,
        "health_status": "WARNING",
        "days_to_failure": 4.0,
        "fault_probability": 0.512,
        "suspected_failure": "Gearbox Wear",
    }
    assert request.instructions == TESTED_CHANNEL_TEXT
    assert request.options == CHANNEL_OPTIONS


def test_a_lead_time_past_the_horizon_is_sent_as_the_no_failure_value() -> None:
    """ML1 can say 10.2 days or nothing; the model was tested with 8 for both."""
    far = build_channel_request("p", {"turbine_id": 1, "days_to_failure": 10.2})
    none = build_channel_request("p", {"turbine_id": 1, "days_to_failure": None})
    missing = build_channel_request("p", {"turbine_id": 1})

    assert far.state["days_to_failure"] == 8.0
    assert none.state["days_to_failure"] == 8.0
    assert missing.state["days_to_failure"] == 8.0


def test_a_plan_request_names_every_plan_and_describes_it() -> None:
    """One option per plan, named plan_A..., with the plan in words."""
    turbines = _turbines()
    requests = build_requests(turbines)
    plans = candidate_plans(requests, WIND)

    request, by_name = build_plan_request(
        "wind_farm_a", turbines, requests, plans, fill_wind(WIND, 7)
    )

    assert sorted(request.options) == [f"plan_{c}" for c in "ABCDEFG"[: len(plans)]]
    assert sorted(map(str, by_name.values())) == sorted(map(str, plans))
    assert request.instructions == PLAN_INSTRUCTIONS
    for name, plan in by_name.items():
        assert f"Turbines saved: {sum(d is not None for d in plan.values())} of 2" in (
            request.options[name]
        )
    assert request.state["wind_forecast"][1] == {"day": 1, "wind_speed_m_s": 3.0}
    assert request.state["turbines"][0] == {
        "turbine_id": 1,
        "health_status": "WARNING",
        "failure_day": 4,
        "fault_probability": 0.51,
        "projected_mwh_7d": 10.0,
    }


def test_the_plan_order_is_the_same_for_the_same_situation() -> None:
    """Shuffled from the park and turbine ids: the same situation, the same letters."""
    turbines = _turbines()
    requests = build_requests(turbines)
    plans = candidate_plans(requests, WIND)
    wind = fill_wind(WIND, 7)

    first = build_plan_request("wind_farm_a", turbines, requests, plans, wind)
    second = build_plan_request("wind_farm_a", turbines, requests, plans, wind)

    assert first[0].options == second[0].options
    assert first[1] == second[1]


def test_the_optimum_does_not_keep_one_letter() -> None:
    """Across parks the optimum lands on different letters, so a letter carries no meaning."""
    turbines = _turbines()
    requests = build_requests(turbines)
    plans = candidate_plans(requests, WIND)
    wind = fill_wind(WIND, 7)

    letters = set()
    for park in ("a", "b", "c", "d", "e", "f", "g", "h"):
        _, by_name = build_plan_request(park, turbines, requests, plans, wind)
        letters.add(next(name for name, plan in by_name.items() if plan == plans[0]))

    assert len(letters) > 1


def test_a_turbine_with_no_failure_day_is_sent_as_eight() -> None:
    """The state uses the same "none predicted" value as the channel state."""
    turbines = [{**_turbines()[0], "days_to_failure": None}, _turbines()[1]]
    requests = build_requests(turbines)
    plans = candidate_plans(requests, WIND)

    request, _ = build_plan_request("p", turbines, requests, plans, fill_wind(WIND, 7))

    assert request.state["turbines"][0]["failure_day"] == 8
