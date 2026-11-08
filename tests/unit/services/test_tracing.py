"""
# Unit tests for the Langfuse tracing

A fake `langfuse` package stands in for the SDK, so the tests need no extra and send nothing. They
cover what the module promises: off by default, silent without keys or without the SDK, the keys
and the mask handed to the SDK explicitly, the observations of a run, and an SDK that breaks
without taking the run down. The tests under "the real SDK" need the `monitoring` extra and skip
without it: they run the whole graph through the real SDK with an in-memory exporter and read the
spans back, so what Langfuse would receive (nesting, tags, masking, errors) is checked, not assumed.
"""

from collections.abc import Iterator
from contextlib import contextmanager
import inspect
import json
import logging
import sys
import types
from typing import Any
import uuid

from langchain_core.callbacks import BaseCallbackHandler
import pytest

from smarthack.clients.crew_client import get_default_crew_client
from smarthack.clients.decision_client import DecisionClient
from smarthack.services.agent import tracing
from smarthack.services.agent.graph import run_park_dispatch_agent
from tests.conftest import requires_extra


@pytest.fixture(autouse=True)
def _no_registered_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Start every test with nothing registered to hide.

    Other tests run the graph, which registers the crews it reads; that must not leak into the
    expectations here.

    :param monkeypatch: pytest's patcher.
    """
    monkeypatch.setattr(tracing, "_REGISTERED", frozenset())
    monkeypatch.setattr(tracing, "_REGISTERED_PATTERN", None)


class FakeSdk:
    """What the fake `langfuse` package recorded."""

    def __init__(self) -> None:
        """Start with nothing recorded and no failure armed."""
        self.clients: list[Any] = []
        self.observations: list[dict[str, Any]] = []
        self.propagated: list[dict[str, Any]] = []
        self.handlers: list[Any] = []
        self.flushed = 0
        self.fail_on_start = False
        self.fail_on_update = False


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> FakeSdk:
    """
    Put a fake `langfuse` and `langfuse.langchain` in place of the real ones, and tracing on.

    :param monkeypatch: pytest's patcher.

    :returns sdk: The record of what the fake was asked to do.
    """
    record = FakeSdk()

    class Observation:
        """A fake span that remembers its updates."""

        def __init__(self, entry: dict[str, Any]) -> None:
            self.entry = entry

        def update(self, **fields: Any) -> None:
            """Record the update, or fail when armed."""
            if record.fail_on_update:
                raise RuntimeError("update broke")
            self.entry["updates"].append(fields)

    class Langfuse:
        """A fake client."""

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            record.clients.append(self)

        @contextmanager
        def start_as_current_observation(self, **kwargs: Any) -> Iterator[Observation]:
            """Open a recorded span, or fail when armed."""
            if record.fail_on_start:
                raise RuntimeError("start broke")
            entry: dict[str, Any] = {"kwargs": kwargs, "updates": [], "closed": False}
            record.observations.append(entry)
            try:
                yield Observation(entry)
            finally:
                entry["closed"] = True

        def flush(self) -> None:
            """Count the flush."""
            record.flushed += 1

    @contextmanager
    def propagate_attributes(**kwargs: Any) -> Iterator[None]:
        """Record the attributes put on the trace."""
        record.propagated.append(kwargs)
        yield

    class CallbackHandler(BaseCallbackHandler):
        """A fake handler that LangGraph can call and that remembers its key."""

        def __init__(self, public_key: str | None = None) -> None:
            self.public_key = public_key
            record.handlers.append(self)

    module = types.ModuleType("langfuse")
    module.Langfuse = Langfuse  # type: ignore[attr-defined]
    module.propagate_attributes = propagate_attributes  # type: ignore[attr-defined]
    langchain_module = types.ModuleType("langfuse.langchain")
    langchain_module.CallbackHandler = CallbackHandler  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", module)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", langchain_module)
    monkeypatch.setattr(tracing, "_CLIENT", None)
    monkeypatch.setattr(tracing, "_FAILED", None)
    monkeypatch.setattr(tracing, "_WARNED_NO_KEYS", False)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.test/")
    return record


def test_nothing_is_traced_by_default() -> None:
    """With tracing off there is no client, no config for the graph and nothing to flush."""
    assert tracing.get_langfuse() is None
    with tracing.agent_run("p") as run:
        run.update(output="x")
        assert run.config == {}
    with tracing.model_call("jev.x") as call:
        call.update(output="x")
    tracing.flush()


def test_a_missing_key_leaves_tracing_off_and_says_so_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, sdk: FakeSdk
) -> None:
    """Enabled but without a key: no client, one warning, however often it is asked."""
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    with caplog.at_level(logging.WARNING):
        assert tracing.get_langfuse() is None
        assert tracing.get_langfuse() is None

    assert sdk.clients == []
    assert caplog.text.count("a key is missing") == 1


def test_the_keys_url_and_mask_are_handed_to_the_sdk_explicitly(sdk: FakeSdk) -> None:
    """Only `config.py` reads the environment; the SDK gets its settings as arguments."""
    client = tracing.get_langfuse()

    assert client is tracing.get_langfuse()
    assert len(sdk.clients) == 1
    assert sdk.clients[0].kwargs == {
        "public_key": "pk-test",
        "secret_key": "sk-test",
        "base_url": "https://langfuse.test",
        "mask": tracing.mask_sensitive,
    }


def test_a_changed_key_builds_a_new_client(monkeypatch: pytest.MonkeyPatch, sdk: FakeSdk) -> None:
    """The client follows the settings it was built from."""
    tracing.get_langfuse()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-other")
    tracing.get_langfuse()

    assert [c.kwargs["public_key"] for c in sdk.clients] == ["pk-test", "pk-other"]


def test_without_the_extra_tracing_is_off_and_nothing_breaks(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, sdk: FakeSdk
) -> None:
    """A core install with tracing switched on: a warning naming what is missing, no error."""
    monkeypatch.setitem(sys.modules, "langfuse", None)

    with caplog.at_level(logging.WARNING):
        assert tracing.get_langfuse() is None
        with tracing.agent_run("p") as run:
            assert run.config == {}

    assert "Langfuse tracing is off" in caplog.text


def _broken_sdk(error: Exception) -> types.ModuleType:
    """
    Make a `langfuse` package that is installed but fails when its client is imported.

    :param error: What importing `Langfuse` raises.

    :returns module: A module whose `Langfuse` attribute raises `error`.
    """
    module = types.ModuleType("langfuse")

    def fail(name: str) -> Any:
        """Raise on any attribute, the way a failing import inside the package would."""
        raise error

    module.__getattr__ = fail  # type: ignore[method-assign]
    return module


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ModuleNotFoundError("no backoff", name="backoff"), id="a-dependency-missing"),
        pytest.param(ImportError("DLL load failed"), id="a-library-cannot-load"),
        pytest.param(RuntimeError("version clash"), id="not-an-import-error-at-all"),
    ],
)
def test_an_sdk_that_is_installed_but_broken_never_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sdk: FakeSdk,
    error: Exception,
) -> None:
    """Whatever fails while importing the SDK, the sweep finishes and says why tracing is off."""
    monkeypatch.setitem(sys.modules, "langfuse", _broken_sdk(error))

    with caplog.at_level(logging.WARNING):
        result = run_park_dispatch_agent("wind_farm_a", [])

    assert result["audit_summary"]
    assert tracing.get_langfuse() is None
    assert caplog.text.count("the SDK cannot be imported") == 1


def test_an_sdk_that_refuses_to_start_leaves_tracing_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, sdk: FakeSdk
) -> None:
    """A constructor that raises is reported once and not retried on every call."""

    def broken(**kwargs: Any) -> None:
        """Refuse to start."""
        raise RuntimeError("bad host")

    monkeypatch.setattr(sys.modules["langfuse"], "Langfuse", broken)

    with caplog.at_level(logging.WARNING):
        assert tracing.get_langfuse() is None
        assert tracing.get_langfuse() is None

    assert caplog.text.count("could not start") == 1


def test_a_run_opens_a_root_observation_with_the_callback_handler(sdk: FakeSdk) -> None:
    """The root span carries the park, the trace gets its tags, the handler is bound to the key."""
    with tracing.agent_run("wind_farm_a", {"park_id": "wind_farm_a"}) as run:
        run.update(output={"decisions": 2})
        assert [type(h).__name__ for h in run.config["callbacks"]] == ["CallbackHandler"]
        assert run.config["callbacks"][0].public_key == "pk-test"

    (root,) = sdk.observations
    assert root["kwargs"] == {
        "as_type": "span",
        "name": "park-dispatch",
        "input": {"park_id": "wind_farm_a"},
    }
    assert root["updates"] == [{"output": {"decisions": 2}}]
    assert root["closed"] is True
    assert sdk.propagated == [
        {"tags": ["park:wind_farm_a"], "metadata": {"park_id": "wind_farm_a"}}
    ]


def test_an_exception_in_the_block_is_not_hidden(sdk: FakeSdk) -> None:
    """The trace closes and the exception goes on: tracing never swallows a failure."""
    with pytest.raises(ValueError, match="boom"):
        with tracing.agent_run("p"):
            raise ValueError("boom")

    assert sdk.observations[0]["closed"] is True


def test_a_sdk_that_breaks_while_opening_does_not_stop_the_run(
    caplog: pytest.LogCaptureFixture, sdk: FakeSdk
) -> None:
    """The block still runs, with an empty config, and the failure is logged."""
    sdk.fail_on_start = True
    ran = False

    with caplog.at_level(logging.WARNING):
        with tracing.agent_run("p") as run:
            ran = True
            assert run.config == {}

    assert ran is True
    assert "could not open a trace" in caplog.text


def test_a_sdk_that_breaks_on_update_does_not_stop_the_run(
    caplog: pytest.LogCaptureFixture, sdk: FakeSdk
) -> None:
    """A failed update is logged and the block goes on."""
    sdk.fail_on_update = True

    with caplog.at_level(logging.WARNING):
        with tracing.model_call("jev.x") as call:
            call.update(output="x")

    assert "could not be updated" in caplog.text


def test_flush_reaches_the_sdk(sdk: FakeSdk) -> None:
    """A short run ends with a flush, so its trace is not lost."""
    tracing.flush()

    assert sdk.flushed == 1


def test_masking_hides_what_reaches_a_crew_by_key() -> None:
    """Phone, email and name keys are masked wherever they sit, whatever the value."""
    data = {
        "crew_name": "Ion Popescu",
        "assigned_crew_name": "Ion Popescu",
        "contact_phone": "+1-555-0101",
        "nested": [{"recipient_email": "a@b.com", "turbine_id": 3}],
        "voice": {"phone_number": "anything"},
    }

    masked = tracing.mask_sensitive(data=data)

    assert masked == {
        "crew_name": "[masked]",
        "assigned_crew_name": "[masked]",
        "contact_phone": "[masked]",
        "nested": [{"recipient_email": "[masked]", "turbine_id": 3}],
        "voice": {"phone_number": "[masked]"},
    }
    assert data["contact_phone"] == "+1-555-0101"


def test_masking_hides_what_reaches_a_crew_inside_text() -> None:
    """An address or an international number in free text is masked; dates and numbers are not."""
    text = "Call +1-555-0101 or mail alpha.crew@windfarma.com about 2026-11-08, p=0.95, 3.2 days."

    assert tracing.mask_sensitive(data=text) == (
        "Call [masked] or mail [masked] about 2026-11-08, p=0.95, 3.2 days."
    )


def test_masking_leaves_other_values_alone() -> None:
    """Numbers, booleans and None pass through unchanged."""
    assert tracing.mask_sensitive(data=[1, 2.5, True, None]) == [1, 2.5, True, None]


def test_the_decision_model_calls_are_traced_inside_the_run(
    monkeypatch: pytest.MonkeyPatch, sdk: FakeSdk
) -> None:
    """A run in shadow mode gives a root, a plan question and one channel question per turbine."""

    class Model(DecisionClient):
        """A model that always answers 0.9 for the first option."""

        def __init__(self) -> None:
            super().__init__("http://fake.test")

        def choice(self, state: Any, instructions: str, options: Any) -> dict[str, float]:
            """Answer with the first option."""
            keys = list(options)
            return {k: (0.9 if i == 0 else 0.1 / (len(keys) - 1)) for i, k in enumerate(keys)}

    monkeypatch.setattr("smarthack.services.agent.graph.get_default_decision_client", Model)
    monkeypatch.setattr(
        "smarthack.services.agent.graph.get_daily_wind_forecast",
        lambda park_id, days: [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0],
    )
    monkeypatch.setattr(
        "smarthack.services.agent.graph.predict_wind_power_mwh", lambda **kwargs: 50.0
    )
    items = [
        {
            "turbine_id": tid,
            "park_id": "wind_farm_a",
            "health_status": "WARNING",
            "fault_probability": 0.5,
            "days_to_failure": 4.0,
            "suspected_failure": "Gearbox Wear",
            "recommended_action": "Inspect.",
            "needs_repair": True,
        }
        for tid in (1, 2)
    ]

    run_park_dispatch_agent("wind_farm_a", items)

    names = [o["kwargs"]["name"] for o in sdk.observations]
    assert names == ["park-dispatch", "jev.repair_plan", "jev.alert_channel", "jev.alert_channel"]
    assert all(o["closed"] for o in sdk.observations)
    plan = sdk.observations[1]
    assert plan["kwargs"]["input"]["mode"] == "umbra"
    assert plan["updates"][-1]["output"]["source"] == "rule"
    assert sdk.observations[0]["updates"][-1]["output"]["decisions"] == 2
    assert sdk.flushed == 1


def test_registered_texts_are_hidden_wherever_they_appear() -> None:
    """A name or a phone number in any format is masked in text once the crews are registered."""
    tracing.register_sensitive(["Ion Popescu", "0721 234 567", "ion@firma.ro", 7, None])

    text = "Ion Popescu, tel 0721 234 567, mail ion@firma.ro, turbine 3 on 2026-11-08."

    assert (
        tracing.mask_sensitive(data=text)
        == "[masked], tel [masked], mail [masked], turbine 3 on 2026-11-08."
    )
    assert tracing.mask_sensitive(data={"note": ["see Ion Popescu"]}) == {"note": ["see [masked]"]}


def test_unregistered_text_and_short_values_are_left_alone() -> None:
    """Only what was registered is hidden, and nothing shorter than four characters is."""
    tracing.register_sensitive(["Ion", "  ", ""])

    assert tracing.mask_sensitive(data="Ion went to Ionel") == "Ion went to Ionel"


def test_a_full_name_is_replaced_whole_before_a_part_of_it() -> None:
    """With a name and its first word both registered, the longer one wins."""
    tracing.register_sensitive(["Maria Ionescu", "Maria"])

    assert tracing.mask_sensitive(data="Maria Ionescu and Maria") == "[masked] and [masked]"


def test_registering_again_adds_to_what_is_hidden() -> None:
    """A second park's crews do not make the first park's names visible."""
    tracing.register_sensitive(["Ion Popescu"])
    tracing.register_sensitive(["Ana Marin"])

    assert tracing.mask_sensitive(data="Ion Popescu, Ana Marin") == "[masked], [masked]"


def test_reading_the_crews_registers_their_names_phones_and_emails() -> None:
    """The graph registers what it loads, so the texts built from it are masked in a trace."""
    get_default_crew_client().reset_crews()

    run_park_dispatch_agent("wind_farm_a", [])

    text = "Alpha Response Team: +1-555-0101, alpha.crew@windfarma.com"
    assert tracing.mask_sensitive(data=text) == "[masked]: [masked], [masked]"


def test_the_run_input_has_no_count_when_the_agent_reads_the_triage_itself(
    monkeypatch: pytest.MonkeyPatch, sdk: FakeSdk
) -> None:
    """Without triage items given, there is no count to show yet, and none is invented."""
    monkeypatch.setattr(
        "smarthack.services.agent.graph.get_turbines_needing_attention", lambda **kwargs: []
    )

    run_park_dispatch_agent("wind_farm_a")
    run_park_dispatch_agent("wind_farm_a", [])

    first, second = sdk.observations[0], sdk.observations[1]
    assert first["kwargs"]["input"] == {"park_id": "wind_farm_a"}
    assert second["kwargs"]["input"] == {"park_id": "wind_farm_a", "triage_items": 0}


def _patch_agent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """
    Make a run of the graph deterministic and offline, with a model that favours option one.

    :param monkeypatch: pytest's patcher.

    :returns items: Three failing turbines of `wind_farm_a`, one of them CRITICAL.
    """

    class Model(DecisionClient):
        """A model that always puts 0.9 on the first option."""

        def __init__(self) -> None:
            super().__init__("http://fake.test")

        def choice(self, state: Any, instructions: str, options: Any) -> dict[str, float]:
            """Answer with the first option."""
            keys = list(options)
            return {k: (0.9 if i == 0 else 0.1 / (len(keys) - 1)) for i, k in enumerate(keys)}

    monkeypatch.setattr("smarthack.services.agent.graph.get_default_decision_client", Model)
    monkeypatch.setattr(
        "smarthack.services.agent.graph.get_daily_wind_forecast",
        lambda park_id, days: [8.0, 3.0, 9.0, 5.0, 2.0, 7.0, 6.0],
    )
    monkeypatch.setattr(
        "smarthack.services.agent.graph.predict_wind_power_mwh", lambda **kwargs: 50.0
    )
    get_default_crew_client().reset_crews()
    return [
        {
            "turbine_id": tid,
            "park_id": "wind_farm_a",
            "health_status": status,
            "fault_probability": 0.6,
            "days_to_failure": days,
            "suspected_failure": "Gearbox Wear",
            "recommended_action": "Inspect.",
            "needs_repair": True,
        }
        for tid, status, days in ((0, "CRITICAL", 0.8), (1, "WARNING", 3.2), (2, "WARNING", 3.9))
    ]


@pytest.fixture
def real_sdk(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """
    Build the real Langfuse client with an in-memory exporter, and make tracing use it.

    Nothing is sent: the exporter keeps the spans, and the server address is a closed local port.
    Each test gets its own public key, because the SDK keeps one client per key.

    :param monkeypatch: pytest's patcher.

    :returns exporter: The `InMemorySpanExporter` that receives every finished span.
    """
    from langfuse import Langfuse
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    public_key = f"pk-lf-{uuid.uuid4().hex}"
    secret_key, base_url = "sk-lf-test", "http://127.0.0.1:9"
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", public_key)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", secret_key)
    monkeypatch.setenv("LANGFUSE_BASE_URL", base_url)
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        mask=tracing.mask_sensitive,
        span_exporter=exporter,
        flush_at=1,
    )
    monkeypatch.setattr(tracing, "_CLIENT", ((public_key, secret_key, base_url), client))
    yield exporter
    client.shutdown()


@requires_extra("monitoring")
def test_the_real_sdk_nests_the_model_calls_under_their_nodes(
    monkeypatch: pytest.MonkeyPatch, real_sdk: Any
) -> None:
    """One trace: the run, then the graph, then each node, with the model calls inside theirs."""
    items = _patch_agent(monkeypatch)

    run_park_dispatch_agent("wind_farm_a", items)

    spans = real_sdk.get_finished_spans()
    by_id = {span.context.span_id: span for span in spans}

    def parent_name(name: str) -> set[str | None]:
        """Names of the parents of every span called `name`."""
        return {by_id[s.parent.span_id].name if s.parent else None for s in spans if s.name == name}

    assert len({span.context.trace_id for span in spans}) == 1
    assert [span.name for span in spans if span.parent is None] == ["park-dispatch"]
    assert parent_name("LangGraph") == {"park-dispatch"}
    assert parent_name("jev.repair_plan") == {"choose_repair_plan"}
    assert parent_name("jev.alert_channel") == {"decide_and_dispatch_alerts"}
    assert sum(span.name == "jev.alert_channel" for span in spans) == 3


@requires_extra("monitoring")
def test_the_real_sdk_puts_the_park_on_every_span(
    monkeypatch: pytest.MonkeyPatch, real_sdk: Any
) -> None:
    """Every observation of the run carries the park tag and the park id, so one park can be found."""
    items = _patch_agent(monkeypatch)

    run_park_dispatch_agent("wind_farm_a", items)

    spans = real_sdk.get_finished_spans()
    assert spans
    for span in spans:
        assert span.attributes["langfuse.trace.tags"] == ("park:wind_farm_a",), span.name
        assert span.attributes["langfuse.trace.metadata.park_id"] == "wind_farm_a", span.name


@requires_extra("monitoring")
def test_the_real_sdk_never_receives_a_name_phone_or_email(
    monkeypatch: pytest.MonkeyPatch, real_sdk: Any
) -> None:
    """Across every attribute of every span, nothing that reaches a crew member is left."""
    items = _patch_agent(monkeypatch)

    run_park_dispatch_agent("wind_farm_a", items)

    stored = json.dumps(
        [dict(span.attributes) for span in real_sdk.get_finished_spans()], default=str
    )
    for crew_data in ("+1-555", "@", "windfarma.com", "Alpha Response Team", "Beta Response Team"):
        assert crew_data not in stored, crew_data
    assert stored.count("[masked]") > 0


@requires_extra("monitoring")
def test_the_real_sdk_marks_a_failed_run_and_leaves_nothing_open(
    monkeypatch: pytest.MonkeyPatch, real_sdk: Any
) -> None:
    """The exception reaches the caller, the root is an error, and every span is closed."""

    def explode(**kwargs: Any) -> None:
        """Fail the way a database does."""
        raise RuntimeError("db exploded")

    monkeypatch.setattr("smarthack.services.agent.graph.get_turbines_needing_attention", explode)

    with pytest.raises(RuntimeError, match="db exploded"):
        run_park_dispatch_agent("wind_farm_a")

    spans = real_sdk.get_finished_spans()
    (root,) = [span for span in spans if span.parent is None]
    assert root.status.status_code.name == "ERROR"
    assert [event.name for event in root.events] == ["exception"]
    assert all(span.end_time is not None for span in spans)


@requires_extra("monitoring")
def test_the_real_sdk_takes_what_is_handed_to_it() -> None:
    """The arguments of `Langfuse(...)` and the callback handler are the ones the SDK declares."""
    from langfuse import Langfuse, propagate_attributes
    from langfuse.langchain import CallbackHandler

    params = inspect.signature(Langfuse.__init__).parameters
    assert {"public_key", "secret_key", "base_url", "mask"} <= set(params)
    assert "public_key" in inspect.signature(CallbackHandler.__init__).parameters
    assert {"tags", "metadata"} <= set(inspect.signature(propagate_attributes).parameters)
