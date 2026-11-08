"""
# Decision model client

Synchronous HTTP client for the local decision model server (`experiments/decision_model`, started
with `uv run python -I -m decision_model.server`), which serves a Jev-style model in the System One
format: a `state` and one typed `choice` question in, one probability per option out.

The client trusts nothing it is sent back. An answer that does not name exactly the options asked,
holds a probability outside 0 to 1, or does not add up to 1 is an error, the same as a timeout or a
server that is down. Every failure raises `DecisionModelError`, so the caller has one thing to
catch and falls back to the rule.

The following can be imported from this module:
- `DecisionClient`
- `DecisionModelError`
- `get_default_decision_client`
"""

from collections.abc import Mapping
import math
from typing import Any

import httpx

from smarthack import config
from smarthack.constants import DECISION_CONNECT_TIMEOUT_SECONDS, DECISION_TIMEOUT_SECONDS

#: Path of the System One endpoint on the decision model server.
_ENDPOINT = "/v1/systemone"

#: Key of the only question of a request.
_QUESTION = "q"

#: How far the probabilities of an answer may be from adding up to 1.
_SUM_TOLERANCE = 0.01


class DecisionModelError(Exception):
    """The decision model could not give a usable answer: down, too slow, or malformed."""


class DecisionClient:
    """
    Client for one local decision model server.

    Holds no connection state between calls beyond the HTTP client's own pool.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = DECISION_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """
        Create a client for the server at `base_url`.

        :param base_url: Server address, such as `http://127.0.0.1:8765`.
        :param timeout: Seconds to wait for an answer; opening the connection gets at most
            `DECISION_CONNECT_TIMEOUT_SECONDS` of it.
        :param transport: An `httpx` transport, to answer in tests without a network.
        """
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, DECISION_CONNECT_TIMEOUT_SECONDS)),
            transport=transport,
        )

    def choice(
        self, state: Mapping[str, Any], instructions: str, options: Mapping[str, str]
    ) -> dict[str, float]:
        """
        Ask the model to pick one of the options.

        :param state: The facts the question is about, sent as is.
        :param instructions: The question, in words.
        :param options: Option key to its description, in the order to present them.

        :returns probabilities: One probability per option key, each in 0 to 1, summing to 1.
        :raises DecisionModelError: When the server is down, too slow, answers with an error
            status, or sends anything but a well-formed answer to this question.
        """
        body = {
            "state": dict(state),
            "questions": {
                _QUESTION: {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": dict(options),
                }
            },
        }
        try:
            response = self._http.post(self._base_url + _ENDPOINT, json=body)
        except httpx.TimeoutException as exc:
            raise DecisionModelError(f"decision model timed out: {exc!r}") from exc
        except httpx.HTTPError as exc:
            raise DecisionModelError(f"decision model unreachable: {exc!r}") from exc
        if response.status_code != 200:
            raise DecisionModelError(f"decision model answered HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DecisionModelError("decision model sent invalid JSON") from exc
        return _probabilities(payload, list(options))

    def close(self) -> None:
        """Close the underlying HTTP connections."""
        self._http.close()


def _probabilities(payload: Any, keys: list[str]) -> dict[str, float]:
    """
    Pull the probabilities of the question out of an answer and check them.

    :param payload: The decoded JSON of the answer.
    :param keys: The option keys that were asked about.

    :returns probabilities: Option key to probability, in the order of `keys`.
    :raises DecisionModelError: When the answer is not shaped as agreed or its numbers are wrong.
    """
    try:
        raw = payload["answers"][_QUESTION]["probabilities"]
    except (KeyError, TypeError) as exc:
        raise DecisionModelError("decision model answer has no probabilities") from exc
    if not isinstance(raw, dict) or set(raw) != set(keys):
        raise DecisionModelError(f"decision model answered options {raw!r}, asked {keys}")
    values: dict[str, float] = {}
    for key in keys:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DecisionModelError(f"probability of {key!r} is not a number: {value!r}")
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise DecisionModelError(f"probability of {key!r} is out of range: {value!r}")
        values[key] = float(value)
    if abs(sum(values.values()) - 1.0) > _SUM_TOLERANCE:
        raise DecisionModelError(f"probabilities add up to {sum(values.values()):.4f}, not 1")
    return values


_GLOBAL_DECISION_CLIENT: DecisionClient | None = None
_GLOBAL_DECISION_URL: str | None = None


def get_default_decision_client() -> DecisionClient | None:
    """
    Return the shared client, or None when the decision model is switched off.

    With the model off (`DECISION_MODEL_ENABLED`) no client exists, so no HTTP call can happen.
    The client is rebuilt when the configured URL changes.

    :returns client: The shared `DecisionClient`, or None when disabled.
    """
    global _GLOBAL_DECISION_CLIENT, _GLOBAL_DECISION_URL
    if not config.decision_model_enabled():
        return None
    url = config.decision_model_url()
    if _GLOBAL_DECISION_CLIENT is None or _GLOBAL_DECISION_URL != url:
        if _GLOBAL_DECISION_CLIENT is not None:
            _GLOBAL_DECISION_CLIENT.close()
        _GLOBAL_DECISION_CLIENT = DecisionClient(url)
        _GLOBAL_DECISION_URL = url
    return _GLOBAL_DECISION_CLIENT


__all__ = ["DecisionClient", "DecisionModelError", "get_default_decision_client"]
