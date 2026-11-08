"""
# Unit tests for the decision model client

Answers come from an `httpx` mock transport, so no server runs. The client must turn every failure,
a server that is down, too slow, or sending anything but a well-formed answer, into the one error
the agent catches.
"""

import json
from typing import Any

import httpx
import pytest

from smarthack.clients import decision_client
from smarthack.clients.decision_client import (
    DecisionClient,
    DecisionModelError,
    get_default_decision_client,
)

OPTIONS = {"a": "Option A.", "b": "Option B."}


def _client(handler: Any) -> DecisionClient:
    """
    Build a client whose server is a function.

    :param handler: Takes the request and returns an `httpx.Response`, or raises.

    :returns client: A client that answers through `handler`.
    """
    return DecisionClient("http://model.test/", transport=httpx.MockTransport(handler))


def _answer(probabilities: Any, status: int = 200) -> httpx.Response:
    """
    Build the server's answer to the one question.

    :param probabilities: What goes under `probabilities`.
    :param status: HTTP status.

    :returns response: The response.
    """
    return httpx.Response(status, json={"answers": {"q": {"probabilities": probabilities}}})


def test_the_request_is_a_system_one_question() -> None:
    """State, one `choice` question named q, options as criteria, sent to /v1/systemone."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _answer({"a": 0.25, "b": 0.75})

    result = _client(handler).choice({"park_id": "p"}, "Which?", OPTIONS)

    assert result == {"a": 0.25, "b": 0.75}
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "http://model.test/v1/systemone"
    assert json.loads(seen[0].content) == {
        "state": {"park_id": "p"},
        "questions": {
            "q": {"type": "choice", "instructions": "Which?", "criteria": OPTIONS},
        },
    }


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(_answer({"a": 0.5, "b": 0.5}, status=500), id="server-error"),
        pytest.param(_answer({"a": 0.5, "b": 0.5}, status=422), id="refused-question"),
        pytest.param(httpx.Response(200, content=b"not json"), id="invalid-json"),
        pytest.param(httpx.Response(200, json={"answers": {}}), id="no-answer-to-q"),
        pytest.param(httpx.Response(200, json=["x"]), id="wrong-shape"),
        pytest.param(_answer({"a": 0.5}), id="missing-option"),
        pytest.param(_answer({"a": 0.5, "b": 0.3, "c": 0.2}), id="extra-option"),
        pytest.param(_answer({"a": 1.2, "b": -0.2}), id="out-of-range"),
        pytest.param(_answer({"a": 0.3, "b": 0.3}), id="does-not-add-up"),
        pytest.param(_answer({"a": "0.5", "b": "0.5"}), id="not-numbers"),
        pytest.param(_answer({"a": True, "b": False}), id="booleans"),
        pytest.param(_answer([0.5, 0.5]), id="list-not-mapping"),
    ],
)
def test_an_unusable_answer_is_a_decision_model_error(response: httpx.Response) -> None:
    """Whatever is wrong with the answer, the caller sees one kind of error."""
    with pytest.raises(DecisionModelError):
        _client(lambda request: response).choice({}, "Which?", OPTIONS)


def test_probabilities_that_add_up_within_the_tolerance_are_accepted() -> None:
    """Rounding in the server's answer is not an error."""
    result = _client(lambda request: _answer({"a": 0.333, "b": 0.664})).choice({}, "?", OPTIONS)

    assert result == {"a": 0.333, "b": 0.664}


def test_a_timeout_is_a_decision_model_error() -> None:
    """A server too slow to answer must not stall the sweep."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DecisionModelError, match="timed out"):
        _client(handler).choice({}, "Which?", OPTIONS)


def test_a_server_that_is_down_is_a_decision_model_error() -> None:
    """Connection refused is reported, not raised as an httpx error."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DecisionModelError, match="unreachable"):
        _client(handler).choice({}, "Which?", OPTIONS)


def test_the_connection_gets_less_time_than_the_whole_call() -> None:
    """A server that is not running is noticed in 2 s, not 10."""
    client = DecisionClient("http://model.test")

    timeout = client._http.timeout

    assert timeout.read == 10.0
    assert timeout.connect == 2.0


def test_there_is_no_client_while_the_model_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the model off, no client exists, so no HTTP call can be made."""
    assert get_default_decision_client() is None
    monkeypatch.setenv("DECISION_MODEL_ENABLED", "false")
    assert get_default_decision_client() is None


def test_the_default_client_follows_the_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """On, the client is shared; a new URL builds a new one."""
    monkeypatch.setenv("DECISION_MODEL_ENABLED", "true")
    monkeypatch.setenv("DECISION_MODEL_URL", "http://one.test/")

    first = get_default_decision_client()
    assert first is get_default_decision_client()
    assert first is not None and first._base_url == "http://one.test"

    monkeypatch.setenv("DECISION_MODEL_URL", "http://two.test")
    second = get_default_decision_client()
    assert second is not first
    assert second is not None and second._base_url == "http://two.test"
    second.close()
    monkeypatch.setattr(decision_client, "_GLOBAL_DECISION_CLIENT", None)


def test_the_prompt_tokens_the_server_counts_are_kept() -> None:
    """A `usage.prompt_tokens` in the answer shows in `last_prompt_tokens`; before a call, None."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "answers": {
                "q": {"probabilities": {"a": 0.5, "b": 0.5}, "usage": {"prompt_tokens": 309}}
            }
        }
        return httpx.Response(200, json=body)

    client = _client(handler)
    assert client.last_prompt_tokens is None

    client.choice({}, "Which?", OPTIONS)

    assert client.last_prompt_tokens == 309


@pytest.mark.parametrize(
    "usage", [None, {}, {"prompt_tokens": -1}, {"prompt_tokens": "9"}, {"prompt_tokens": True}]
)
def test_a_missing_or_bad_token_count_never_fails_the_decision(usage: Any) -> None:
    """The count is optional: the probabilities still come back and the count is None."""
    answer: dict[str, Any] = {"probabilities": {"a": 0.5, "b": 0.5}}
    if usage is not None:
        answer["usage"] = usage

    client = _client(lambda request: httpx.Response(200, json={"answers": {"q": answer}}))

    assert client.choice({}, "Which?", OPTIONS) == {"a": 0.5, "b": 0.5}
    assert client.last_prompt_tokens is None
