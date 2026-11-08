"""
# Unit tests for the model decisions

A fake client stands in for the model, so each test says exactly what the model answers. Covers
when the model is not asked, shadow against active mode, the check on a plan that saves fewer
turbines, the hard rule for CRITICAL turbines and every kind of failure.
"""

from collections.abc import Callable, Mapping
import logging
from typing import Any

import pytest

from smarthack.clients.decision_client import DecisionClient, DecisionModelError
from smarthack.schemas.dispatch import AlertChannel
from smarthack.services.agent.model_decisions import choose_channel, choose_plan

WIND = [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0]

#: A reply: probabilities for the options, or an error to raise.
Reply = Callable[[Mapping[str, str]], dict[str, float] | Exception]


class FakeClient(DecisionClient):
    """A decision client that answers from a function and remembers what it was asked."""

    def __init__(self, reply: Reply) -> None:
        """
        Create the fake.

        :param reply: Takes the options asked about; returns probabilities, or an exception to raise.
        """
        super().__init__("http://fake.test")
        self.reply = reply
        self.asked: list[dict[str, Any]] = []

    def choice(
        self, state: Mapping[str, Any], instructions: str, options: Mapping[str, str]
    ) -> dict[str, float]:
        """
        Answer from the function.

        :param state: Recorded.
        :param instructions: Recorded.
        :param options: Recorded and passed to the reply function.

        :returns probabilities: The reply.
        :raises DecisionModelError: When the reply is an exception.
        """
        self.asked.append({"state": state, "instructions": instructions, "options": options})
        result = self.reply(options)
        if isinstance(result, Exception):
            raise result
        return result


def _favor(text: str) -> Reply:
    """
    Make a reply that puts 0.8 on the first option whose description contains `text`.

    :param text: A phrase of the option to favour.

    :returns reply: The reply function.
    """

    def reply(options: Mapping[str, str]) -> dict[str, float]:
        """Spread 0.2 over the other options and give the favourite 0.8."""
        chosen = next(name for name, description in options.items() if text in description)
        others = [name for name in options if name != chosen]
        return {name: (0.8 if name == chosen else 0.2 / len(others)) for name in options}

    return reply


def _channel_for(channel: AlertChannel) -> Reply:
    """
    Make a reply that puts 0.9 on a channel.

    :param channel: The channel the fake model picks.

    :returns reply: The reply function.
    """

    def reply(options: Mapping[str, str]) -> dict[str, float]:
        """Give the channel 0.9 and share the rest."""
        return {name: (0.9 if name == channel.value else 0.05) for name in options}

    return reply


def _down(_: Mapping[str, str]) -> Exception:
    """A reply that fails the way a server that is down does."""
    return DecisionModelError("down")


def _turbine(turbine_id: int, days: float | None, mwh: float | None) -> dict[str, Any]:
    """
    Build a failing turbine.

    :param turbine_id: Turbine identifier.
    :param days: Predicted days to failure.
    :param mwh: Projected output.

    :returns item: Triage dictionary.
    """
    item: dict[str, Any] = {
        "turbine_id": turbine_id,
        "health_status": "WARNING",
        "fault_probability": 0.5,
        "days_to_failure": days,
    }
    if mwh is not None:
        item["projected_mwh_7d"] = mwh
    return item


#: Two turbines, same deadline: the optimum and the most-urgent-first plan save both.
EQUAL = [_turbine(1, 4.0, 10.0), _turbine(2, 4.0, 40.0)]
#: Turbine 1 can only be repaired today. "Most distant first" gives turbine 3 today and loses it.
TIGHT = [_turbine(1, 1.0, 40.0), _turbine(3, 5.0, 10.0)]

OPTIMUM_EQUAL = {2: 1, 1: 3}
OTHER_EQUAL = {2: 0, 1: 1}


def test_the_model_is_not_asked_when_it_is_off() -> None:
    """No client: the optimum, and nothing to call."""
    decision = choose_plan("p", EQUAL, WIND, client=None, mode="activ")

    assert decision.chosen == OPTIMUM_EQUAL
    assert decision.record["reason"] == "disabled"
    assert decision.record["source"] == "rule"
    assert decision.model_down is False


def test_the_model_is_not_asked_once_it_is_down() -> None:
    """A model that failed earlier in the run is skipped, not retried."""
    client = FakeClient(_favor("day 0"))

    decision = choose_plan("p", EQUAL, WIND, client=client, mode="activ", model_down=True)

    assert client.asked == []
    assert decision.chosen == OPTIMUM_EQUAL
    assert decision.record["reason"] == "model_down"


def test_the_model_is_not_asked_when_every_plan_is_the_same() -> None:
    """One distinct plan leaves nothing to choose."""
    client = FakeClient(_favor("day"))
    lone = [_turbine(1, 4.0, 10.0)]

    decision = choose_plan("p", lone, [1.0, 5.0, 6.0, 7.0, 8.0, 9.0, 9.0], client, "activ")

    assert client.asked == []
    assert decision.record["reason"] == "one_plan"


@pytest.mark.parametrize("wind", [[], [None, None, None]])
def test_the_model_is_not_asked_without_a_wind_forecast(wind: list[float | None]) -> None:
    """Without wind the plans differ in nothing the model could see."""
    client = FakeClient(_favor("day"))

    decision = choose_plan("p", EQUAL, wind, client, "activ")

    assert client.asked == []
    assert decision.record["reason"] == "no_wind_forecast"


def test_the_model_is_not_asked_without_an_output_estimate() -> None:
    """Plans cannot be compared on output lost when no turbine has an estimate."""
    client = FakeClient(_favor("day"))
    no_estimate = [_turbine(1, 4.0, None), _turbine(2, 4.0, None)]

    decision = choose_plan("p", no_estimate, WIND, client, "activ")

    assert client.asked == []
    assert decision.record["reason"] == "no_output_estimate"


def test_in_shadow_mode_the_optimum_wins_and_the_pick_is_recorded() -> None:
    """The model prefers the other plan; `umbra` logs it and changes nothing."""
    client = FakeClient(_favor("day 0 turbine 2"))

    decision = choose_plan("p", EQUAL, WIND, client, mode="umbra")

    assert len(client.asked) == 1
    assert decision.chosen == OPTIMUM_EQUAL
    assert decision.record["source"] == "rule"
    assert decision.record["model_pick"] != decision.record["chosen"]
    assert decision.record["probabilities"][decision.record["model_pick"]] == 0.8
    assert decision.record["latency_ms"] >= 0
    assert decision.model_down is False


def test_in_active_mode_a_pick_that_saves_as_many_turbines_is_followed() -> None:
    """The other plan saves both turbines and loses more output: accepted, a known cost."""
    client = FakeClient(_favor("day 0 turbine 2"))

    decision = choose_plan("p", EQUAL, WIND, client, mode="activ")

    assert decision.chosen == OTHER_EQUAL
    assert decision.record["source"] == "model"
    assert decision.record["chosen"] == decision.record["model_pick"]
    assert decision.record["pick_output_lost"] > decision.record["optimum_output_lost"]


def test_in_active_mode_a_pick_that_saves_fewer_turbines_is_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The code check keeps the optimum when the pick loses a turbine, and says so."""
    client = FakeClient(_favor("Turbines saved: 1 of 2"))

    with caplog.at_level(logging.WARNING):
        decision = choose_plan("p", TIGHT, WIND, client, mode="activ")

    assert decision.chosen == {1: 0, 3: 4}
    assert decision.record["source"] == "rule_fallback"
    assert decision.record["reason"] == "rejected"
    assert decision.record["pick_saved"] == 1
    assert decision.record["optimum_saved"] == 2
    assert "using the optimum" in caplog.text


@pytest.mark.parametrize(("mode", "source"), [("activ", "rule_fallback"), ("umbra", "rule")])
def test_a_failing_model_leaves_the_optimum_and_is_marked_down(mode: str, source: str) -> None:
    """Any model error falls back to the optimum and tells the caller to stop asking."""
    client = FakeClient(_down)

    decision = choose_plan("p", EQUAL, WIND, client, mode=mode)

    assert decision.chosen == OPTIMUM_EQUAL
    assert decision.model_down is True
    assert decision.record["reason"] == "error"
    assert decision.record["source"] == source


def _item(status: str, days: float | None, probability: float) -> dict[str, Any]:
    """
    Build a triage item for the channel decision.

    :param status: Health status.
    :param days: Days to failure.
    :param probability: Fault probability.

    :returns item: Triage dictionary.
    """
    return {
        "turbine_id": 7,
        "health_status": status,
        "days_to_failure": days,
        "fault_probability": probability,
    }


def test_the_channel_is_the_rule_when_the_model_is_off() -> None:
    """No client: the rule decides, nothing is called."""
    decision = choose_channel("p", _item("WARNING", 4.0, 0.5), client=None, mode="activ")

    assert decision.channel == AlertChannel.EMAIL
    assert decision.record["source"] == "rule"
    assert decision.record["reason"] == "disabled"


def test_in_shadow_mode_the_rule_decides_and_the_model_is_recorded() -> None:
    """The model would phone; the rule says email; the email goes out and both are on record."""
    client = FakeClient(_channel_for(AlertChannel.VOICE_CALL))

    decision = choose_channel("p", _item("WARNING", 4.0, 0.5), client, mode="umbra")

    assert decision.channel == AlertChannel.EMAIL
    assert decision.record["rule"] == AlertChannel.EMAIL.value
    assert decision.record["model"] == AlertChannel.VOICE_CALL.value
    assert decision.record["used"] == AlertChannel.EMAIL.value
    assert decision.record["source"] == "rule"
    assert len(client.asked) == 1


def test_in_active_mode_the_model_decides() -> None:
    """The model's pick is used, and the rule's is kept in the record."""
    client = FakeClient(_channel_for(AlertChannel.NONE))

    decision = choose_channel("p", _item("WARNING", 4.0, 0.5), client, mode="activ")

    assert decision.channel == AlertChannel.NONE
    assert decision.record["source"] == "model"
    assert decision.record["rule"] == AlertChannel.EMAIL.value
    assert decision.record["probabilities"][AlertChannel.NONE.value] == 0.9


def test_a_critical_turbine_is_never_put_to_the_model_in_active_mode() -> None:
    """The hard rule decides; the model is not even asked."""
    client = FakeClient(_channel_for(AlertChannel.NONE))

    decision = choose_channel("p", _item("CRITICAL", 5.0, 0.2), client, mode="activ")

    assert decision.channel == AlertChannel.VOICE_CALL
    assert decision.record["source"] == "hard_rule"
    assert client.asked == []


def test_in_shadow_mode_a_critical_turbine_is_asked_and_a_disagreement_is_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The model is asked so the log shows it; the hard rule still decides."""
    client = FakeClient(_channel_for(AlertChannel.NONE))

    with caplog.at_level(logging.WARNING):
        decision = choose_channel("p", _item("CRITICAL", 5.0, 0.2), client, mode="umbra")

    assert decision.channel == AlertChannel.VOICE_CALL
    assert decision.record["source"] == "hard_rule"
    assert decision.record["model"] == AlertChannel.NONE.value
    assert "hard rule overrides the model" in caplog.text


@pytest.mark.parametrize(
    ("status", "mode", "source"),
    [
        ("WARNING", "activ", "rule_fallback"),
        ("WARNING", "umbra", "rule"),
        ("CRITICAL", "umbra", "hard_rule"),
    ],
)
def test_a_failing_model_leaves_the_rule_and_is_marked_down(
    status: str, mode: str, source: str
) -> None:
    """Whatever the mode, an error means the rule's channel and no more calls."""
    client = FakeClient(_down)

    decision = choose_channel("p", _item(status, 4.0, 0.5), client, mode=mode)

    assert decision.model_down is True
    assert decision.record["reason"] == "error"
    assert decision.record["source"] == source
    expected = AlertChannel.VOICE_CALL if status == "CRITICAL" else AlertChannel.EMAIL
    assert decision.channel == expected


def test_the_channel_is_not_asked_once_the_model_is_down() -> None:
    """After a failure the rest of the run is decided by rule without waiting."""
    client = FakeClient(_channel_for(AlertChannel.NONE))

    decision = choose_channel(
        "p", _item("WARNING", 4.0, 0.5), client, mode="activ", model_down=True
    )

    assert client.asked == []
    assert decision.channel == AlertChannel.EMAIL
    assert decision.record["reason"] == "model_down"


def test_a_turbine_with_no_lead_time_does_not_crash_the_rule() -> None:
    """An explicit None used to break `float()`; it now reads as no failure predicted."""
    decision = choose_channel("p", _item("WATCH", None, 0.1), client=None, mode="umbra")

    assert decision.channel == AlertChannel.EMAIL
