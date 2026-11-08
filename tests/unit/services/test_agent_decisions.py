"""
# Unit tests for the decision model inside the dispatch graph

Runs the whole graph with a fake client in place of the model. Covers shadow against active mode
for the repair plan and the alert channel, a model that goes down mid-run, the order of turbines
taken from the plan, the call that comes with its email, and the turbines ML1 expects to last.
"""

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

import pytest

from smarthack import config
from smarthack.clients.crew_client import get_default_crew_client
from smarthack.clients.decision_client import DecisionClient, DecisionModelError
from smarthack.clients.email_client import get_default_email_client
from smarthack.clients.voice_client import get_default_voice_client
from smarthack.schemas.dispatch import AlertChannel
from smarthack.services.agent.graph import node_rank_and_match_crews, run_park_dispatch_agent
from smarthack.utils.dates import today_in_tz

WIND = [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0]

Reply = Callable[[Mapping[str, str], Mapping[str, Any]], dict[str, float] | Exception]


class FakeClient(DecisionClient):
    """A decision client that answers from a function and remembers what it was asked."""

    def __init__(self, reply: Reply) -> None:
        """
        Create the fake.

        :param reply: Takes the options and the state; returns probabilities or an exception.
        """
        super().__init__("http://fake.test")
        self.reply = reply
        self.asked: list[tuple[str, Mapping[str, Any]]] = []

    def choice(
        self, state: Mapping[str, Any], instructions: str, options: Mapping[str, str]
    ) -> dict[str, float]:
        """
        Answer from the function.

        :param state: Recorded with the kind of question.
        :param instructions: Unused.
        :param options: Passed to the reply function.

        :returns probabilities: The reply.
        :raises DecisionModelError: When the reply is an exception.
        """
        self.asked.append(("plan" if "plan_A" in options else "channel", state))
        result = self.reply(options, state)
        if isinstance(result, Exception):
            raise result
        return result

    def kinds(self) -> list[str]:
        """
        Say what was asked, in order.

        :returns kinds: `"plan"` or `"channel"` for each call.
        """
        return [kind for kind, _ in self.asked]


def _one_hot(option: str) -> Callable[[Mapping[str, str], Mapping[str, Any]], dict[str, float]]:
    """
    Make a reply that puts 0.9 on the option named `option`, or on the plan that contains it.

    :param option: A channel value, or text of a plan description.

    :returns reply: The reply function.
    """

    def reply(options: Mapping[str, str], state: Mapping[str, Any]) -> dict[str, float]:
        """Give the match 0.9 and share the rest."""
        match = next(
            (name for name, text in options.items() if name == option or option in text),
            next(iter(options)),
        )
        return {name: (0.9 if name == match else 0.1 / (len(options) - 1)) for name in options}

    return reply


def _down(options: Mapping[str, str], state: Mapping[str, Any]) -> Exception:
    """A reply that fails the way a server that is down does."""
    return DecisionModelError("down")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Run without an LLM key, with known wind and outputs, and every crew available.

    Output is ten times the turbine id, so the higher id always produces more.

    :param monkeypatch: pytest's patcher.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        "smarthack.services.agent.graph.get_daily_wind_forecast", lambda park_id, days: list(WIND)
    )
    monkeypatch.setattr(
        "smarthack.services.agent.graph.get_turbine_location",
        lambda turbine_id: {"latitude": float(turbine_id), "longitude": 0.0, "capacity_kw": 1.0},
    )
    monkeypatch.setattr(
        "smarthack.services.agent.graph.predict_wind_power_mwh",
        lambda latitude, longitude, forecast_days, capacity_kw: latitude * 10.0,
    )
    get_default_crew_client().reset_crews()
    get_default_email_client().clear_history()
    get_default_voice_client().clear_history()


def _use(monkeypatch: pytest.MonkeyPatch, client: FakeClient | None, mode: str) -> None:
    """
    Put a fake client and a mode in place of the configured ones.

    :param monkeypatch: pytest's patcher.
    :param client: The fake, or None for a model that is off.
    :param mode: `"umbra"` or `"activ"`.
    """
    monkeypatch.setattr(
        "smarthack.services.agent.graph.get_default_decision_client", lambda: client
    )
    monkeypatch.setenv("DECISION_MODEL_MODE", mode)


def _failing(turbine_id: int, days: float | None, status: str = "WARNING") -> dict[str, Any]:
    """
    Build a triage item that needs repair.

    :param turbine_id: Turbine identifier.
    :param days: Predicted days to failure, or None.
    :param status: Health status.

    :returns item: Triage dictionary.
    """
    return {
        "turbine_id": turbine_id,
        "park_id": "wind_farm_a",
        "health_status": status,
        "fault_probability": 0.5,
        "days_to_failure": days,
        "suspected_failure": "Gearbox Wear",
        "recommended_action": "Inspect.",
        "needs_repair": True,
    }


def _days(result: Mapping[str, Any]) -> dict[int, int | None]:
    """
    Read the repair day of each turbine out of the final state.

    :param result: The graph's final state.

    :returns days: Repair day per turbine id.
    """
    return {tid: entry["day"] for tid, entry in result["repair_schedule"].items()}


def test_in_shadow_mode_the_optimum_is_kept_and_the_model_is_only_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model prefers the other plan; nothing changes, and the record shows what it said."""
    client = FakeClient(_one_hot("day 0 turbine 2"))
    _use(monkeypatch, client, "umbra")

    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 4.0), _failing(2, 4.0)])

    assert _days(result) == {2: 1, 1: 3}
    choice = result["repair_plan_choice"]
    assert choice["source"] == "rule"
    assert choice["model_pick"] != choice["chosen"]
    assert client.kinds() == ["plan", "channel", "channel"]
    assert [r["source"] for r in result["channel_decisions"]] == ["rule", "rule"]


def test_in_active_mode_the_plan_follows_the_model_and_the_alerts_name_its_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model's plan becomes the schedule, and the crew is told its dates."""
    client = FakeClient(_one_hot("day 0 turbine 2"))
    _use(monkeypatch, client, "activ")
    today = today_in_tz(config.timezone())

    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 4.0), _failing(2, 4.0)])

    assert _days(result) == {2: 0, 1: 1}
    assert result["repair_plan_choice"]["source"] == "model"
    dates = {d["turbine_id"]: d["repair_date"] for d in result["alert_decisions"]}
    assert dates == {2: today.isoformat(), 1: (today + timedelta(days=1)).isoformat()}
    assert [d["turbine_id"] for d in result["alert_decisions"]] == [2, 1]


def test_in_active_mode_the_channel_follows_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model answers nothing, and the decision records both its pick and the rule's."""
    client = FakeClient(_one_hot(AlertChannel.NONE.value))
    _use(monkeypatch, client, "activ")

    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 6.0)])

    decision = result["alert_decisions"][0]
    assert decision["alert_channel"] == AlertChannel.NONE.value
    assert decision["notification_sent"] is False
    assert result["channel_decisions"][0]["rule"] == AlertChannel.EMAIL.value
    assert get_default_email_client().get_email_history() == []


def test_a_model_that_goes_down_is_called_once_and_the_rule_finishes_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the first failure no node waits on the model again, and every decision is a rule's."""
    client = FakeClient(_down)
    _use(monkeypatch, client, "activ")

    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 4.0), _failing(2, 4.0)])

    assert client.kinds() == ["plan"]
    assert result["decision_model_down"] is True
    assert _days(result) == {2: 1, 1: 3}
    assert {r["reason"] for r in result["channel_decisions"]} == {"model_down"}
    assert [d["alert_channel"] for d in result["alert_decisions"]] == [AlertChannel.EMAIL.value] * 2


def test_a_model_that_fails_on_the_alerts_is_asked_once_for_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plan is fine, the first alert call fails, the other turbine is not asked."""

    def reply(options: Mapping[str, str], state: Mapping[str, Any]) -> dict[str, float] | Exception:
        """Answer the plan, fail the channel."""
        return _one_hot("day")(options, state) if "plan_A" in options else DecisionModelError("x")

    client = FakeClient(reply)
    _use(monkeypatch, client, "umbra")

    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 4.0), _failing(2, 4.0)])

    assert client.kinds() == ["plan", "channel"]
    assert result["decision_model_down"] is True


def test_with_the_model_off_nothing_is_asked_and_the_run_is_the_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default: no client, the optimum and the rule, with the reasons on record."""
    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 4.0), _failing(2, 4.0)])

    assert result["repair_plan_choice"]["reason"] == "disabled"
    assert {r["reason"] for r in result["channel_decisions"]} == {"disabled"}
    assert result["decision_model_down"] is False


def test_a_critical_turbine_gets_the_call_and_the_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """The call alone leaves the crew nothing written: it goes out with the email."""
    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 0.8, "CRITICAL")])

    decision = result["alert_decisions"][0]
    calls = get_default_voice_client().get_call_history()
    emails = get_default_email_client().get_email_history()
    assert decision["alert_channel"] == AlertChannel.VOICE_CALL.value
    assert len(calls) == 1
    assert len(emails) == 1
    assert emails[0]["turbine_id"] == 1
    assert len(result["notifications_dispatched"]) == 2
    assert decision["notification_message"].startswith("Emergency alert")


def test_a_warning_gets_only_the_email() -> None:
    """Email only means no call."""
    run_park_dispatch_agent("wind_farm_a", [_failing(1, 6.0)])

    assert get_default_voice_client().get_call_history() == []
    assert len(get_default_email_client().get_email_history()) == 1


def test_active_mode_never_puts_a_critical_turbine_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model would say nothing; the hard rule still phones, and it is not even asked."""
    client = FakeClient(_one_hot(AlertChannel.NONE.value))
    _use(monkeypatch, client, "activ")

    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 0.8, "CRITICAL")])

    assert client.kinds() == []
    assert result["alert_decisions"][0]["alert_channel"] == AlertChannel.VOICE_CALL.value
    assert result["channel_decisions"][0]["source"] == "hard_rule"


def test_turbines_come_out_in_the_order_the_plan_repairs_them() -> None:
    """Earliest repair day first; the turbine with no day last; crews handed out in that order."""
    state: Any = {
        "failing_turbines": [
            {"turbine_id": 1, "projected_mwh_7d": 10.0},
            {"turbine_id": 2, "projected_mwh_7d": 99.0},
            {"turbine_id": 3, "projected_mwh_7d": 20.0},
            {"turbine_id": 4, "projected_mwh_7d": 5.0},
        ],
        "repair_schedule": {
            1: {"day": 2},
            2: {"day": None},
            3: {"day": 0},
            4: {"day": None},
        },
        "available_crews": [{"crew_id": "c1"}, {"crew_id": "c2"}],
    }

    update = node_rank_and_match_crews(state)

    assert [t["turbine_id"] for t in update["prioritized_turbines"]] == [3, 1, 2, 4]
    assert update["crew_assignments"] == {3: "c1", 1: "c2", 2: "", 4: ""}


def test_turbines_ml1_expects_to_last_do_not_make_a_conflict() -> None:
    """A lead time of 9 days or none is no failure day, so two such turbines never overlap."""
    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 9.0), _failing(2, None)])

    assert result["has_conflict"] is False
    assert result["power_model_invoked"] is False
    assert len(result["alert_decisions"]) == 2
    assert all(d["repair_date"] is not None for d in result["alert_decisions"])


def test_a_turbine_with_no_failure_day_does_not_overlap_with_one_that_has() -> None:
    """Turbine 1 fails on day 6; turbine 2 has none. The old default of 7 would have overlapped."""
    result = run_park_dispatch_agent("wind_farm_a", [_failing(1, 6.5), _failing(2, None)])

    assert result["has_conflict"] is False
