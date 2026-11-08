"""
# Tracing

Sends traces of the dispatch agent to Langfuse, so a run can be opened afterwards and every
decision read in order: what each graph node received and returned, and for each question put to
the local decision model, the options, the probabilities, who decided and how long it took.

Tracing is a write-only side channel. It never changes what the agent decides, and it must never
stop a sweep: it is off unless `LANGFUSE_ENABLED` is on, does nothing without both keys or without
the `monitoring` extra, and any error from the Langfuse SDK is logged once and swallowed. Importing
the package never needs the extra: `langfuse` is imported inside the functions that use it.

Two things are traced. The whole run is one root observation, with the LangGraph callback handler
nested under it, which records every node. Each call to the decision model is an observation of
its own, so its real duration is the model's latency.

Nothing that reaches a crew member leaves the machine: not a phone number, an email address or a
name. `mask_sensitive` is handed to the SDK as its `mask` function and runs on everything the SDK
is about to send. It hides three things, each as `[masked]`:

- the value under a key that holds contact data or a name (`contact_phone`, `crew_name`, ...);
- the phone numbers and email addresses the agent loaded for the park's crews, wherever they turn
  up in text (`register_sensitive`): the names, phones and emails of employees are known exactly
  once the crews are read, and replacing the known text catches a number in any format;
- anything shaped like an email address or an international (`+`) phone number.

Only dictionaries, lists and strings are looked into. A model object left in the graph state would
go through unmasked, so state holds plain dictionaries.

The following can be imported from this module:
- `Trace`
- `agent_run`
- `flush`
- `get_langfuse`
- `mask_sensitive`
- `model_call`
- `register_sensitive`
"""

from collections.abc import Iterable
from contextlib import ExitStack
import logging
import re
import threading
from typing import Any

from smarthack import config

logger = logging.getLogger(__name__)

#: What replaces a masked value.
MASKED = "[masked]"

#: Keys whose value is a way to reach a crew member, or a name, whatever the value looks like.
_SENSITIVE_KEYS = frozenset(
    {
        "phone",
        "phone_number",
        "contact_phone",
        "email",
        "contact_email",
        "recipient_email",
        "recipient_phone",
        "crew_name",
        "assigned_crew_name",
        "full_name",
        "full_nama",
    }
)

#: Shorter values are not registered: a name or number that short would also match inside
#: unrelated words and digits.
_MIN_REGISTERED_LENGTH = 4

#: An email address inside free text.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

#: An international phone number inside free text. It must start with `+`, so a date or a
#: probability is never taken for one.
_PHONE = re.compile(r"\+\d[\d\s().-]{6,}\d")

#: The exact texts to hide, as registered by `register_sensitive`; replaced in every string.
_REGISTERED: frozenset[str] = frozenset()

#: The pattern that finds `_REGISTERED` in text, longest first so a full name is replaced whole
#: before a part of it; None while nothing is registered.
_REGISTERED_PATTERN: re.Pattern[str] | None = None

#: Guards `_REGISTERED`, which several runs in different threads may add to.
_REGISTER_LOCK = threading.Lock()

#: The client built so far, with what it was built from; None before the first call.
_CLIENT: tuple[tuple[str, str, str], Any] | None = None

#: The settings a client already failed to build with, so a bad setting is reported once.
_FAILED: tuple[str, str, str] | None = None

#: Whether the "enabled but no keys" warning was already given.
_WARNED_NO_KEYS = False


def register_sensitive(values: Iterable[Any]) -> None:
    """
    Remember texts that must never be sent, so they are hidden wherever they appear in a string.

    Called when the agent has read the park's crews, with their names, phone numbers and email
    addresses, whatever format the database keeps them in. Values that are not text, or are shorter
    than a few characters, are ignored. The set only grows: it is bounded by the staff of the
    parks.

    :param values: Candidate texts; anything else in the iterable is skipped.
    """
    global _REGISTERED, _REGISTERED_PATTERN
    fresh = {
        value.strip()
        for value in values
        if isinstance(value, str) and len(value.strip()) >= _MIN_REGISTERED_LENGTH
    }
    if fresh <= _REGISTERED:
        return
    with _REGISTER_LOCK:
        merged = _REGISTERED | fresh
        _REGISTERED_PATTERN = re.compile(
            "|".join(re.escape(text) for text in sorted(merged, key=len, reverse=True))
        )
        _REGISTERED = merged


def _mask_text(text: str) -> str:
    """
    Hide the registered texts, email addresses and international phone numbers in a string.

    :param text: Any string.

    :returns masked: The string with each of those replaced by `[masked]`.
    """
    pattern = _REGISTERED_PATTERN
    if pattern is not None:
        text = pattern.sub(MASKED, text)
    return _PHONE.sub(MASKED, _EMAIL.sub(MASKED, text))


def _mask_value(value: Any) -> Any:
    """
    Mask what identifies a crew in a value of any shape.

    :param value: A string, a mapping, a list or tuple of these, or anything else.

    :returns masked: A copy in which sensitive keys and patterns are replaced; values that are
        none of these shapes come back unchanged.
    """
    if isinstance(value, dict):
        return {
            key: MASKED if str(key).lower() in _SENSITIVE_KEYS else _mask_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask_value(item) for item in value]
    if isinstance(value, str):
        return _mask_text(value)
    return value


def mask_sensitive(*, data: Any, **kwargs: Any) -> Any:
    """
    Hide crew names, phone numbers and email addresses from what is sent to Langfuse.

    This is the `mask` function of the SDK: it is called with the data as a keyword argument.

    :param data: Anything the SDK is about to send as the input, output or metadata of an
        observation.
    :param kwargs: Anything else the SDK passes; unused.

    :returns masked: The same data with names, phone numbers and email addresses replaced by
        `[masked]`.
    """
    return _mask_value(data)


def get_langfuse() -> Any | None:
    """
    Return the Langfuse client, or None when tracing is off or cannot work.

    Built once and reused. The keys and URL are passed to the SDK explicitly: only `config.py`
    reads the environment.

    :returns client: A `langfuse.Langfuse`, or None when `LANGFUSE_ENABLED` is off, a key is
        missing, the `monitoring` extra is not installed, or the SDK refused to start.
    """
    global _CLIENT, _FAILED, _WARNED_NO_KEYS
    if not config.langfuse_enabled():
        return None
    settings = (
        config.langfuse_public_key(),
        config.langfuse_secret_key(),
        config.langfuse_base_url(),
    )
    if not settings[0] or not settings[1]:
        if not _WARNED_NO_KEYS:
            logger.warning("LANGFUSE_ENABLED is on but a key is missing: tracing is off")
            _WARNED_NO_KEYS = True
        return None
    if _CLIENT is not None and _CLIENT[0] == settings:
        return _CLIENT[1]
    if _FAILED == settings:
        return None
    try:
        from langfuse import Langfuse
    except Exception as exc:
        # Not only a missing `monitoring` extra: a package that is there but cannot load (a
        # dependency of its own missing, a native library absent) must not stop the sweep either.
        logger.warning("Langfuse tracing is off: the SDK cannot be imported: %r", exc)
        _FAILED = settings
        return None
    try:
        client = Langfuse(
            public_key=settings[0],
            secret_key=settings[1],
            base_url=settings[2],
            mask=mask_sensitive,
        )
    except Exception as exc:
        logger.warning("Langfuse could not start, tracing is off: %s", exc)
        _FAILED = settings
        return None
    _CLIENT = (settings, client)
    return client


class Trace:
    """
    One observation in Langfuse, as a context manager that does nothing when tracing is off.

    Whatever goes wrong inside the SDK is logged and swallowed; whatever goes wrong inside the
    `with` block is never hidden. `config` holds the LangGraph run config to pass to `invoke`:
    empty unless the trace was opened with the callback handler.
    """

    def __init__(
        self,
        name: str,
        input: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, str] | None = None,
        callbacks: bool = False,
    ) -> None:
        """
        Prepare the observation; nothing is sent until the block is entered.

        :param name: Name of the observation in Langfuse.
        :param input: What the observation received.
        :param tags: Tags put on the whole trace.
        :param metadata: String metadata propagated to the whole trace.
        :param callbacks: Whether to give `config` a LangGraph callback handler.
        """
        self.config: dict[str, Any] = {}
        self._name = name
        self._input = input
        self._tags = tags
        self._metadata = metadata
        self._callbacks = callbacks
        self._stack: ExitStack | None = None
        self._observation: Any = None

    def __enter__(self) -> "Trace":
        """
        Open the observation if tracing is on.

        :returns trace: This trace, ready for `update` and, when asked for, `config`.
        """
        client = get_langfuse()
        if client is None:
            return self
        stack = ExitStack()
        try:
            if self._tags or self._metadata:
                from langfuse import propagate_attributes

                stack.enter_context(propagate_attributes(tags=self._tags, metadata=self._metadata))
            self._observation = stack.enter_context(
                client.start_as_current_observation(
                    as_type="span", name=self._name, input=self._input
                )
            )
            if self._callbacks:
                self.config = {"callbacks": [self._handler()]}
        except Exception as exc:
            logger.warning("Langfuse could not open a trace, going on without it: %s", exc)
            self._observation = None
            self.config = {}
            try:
                stack.close()
            except Exception as close_exc:
                logger.warning("Langfuse trace did not close cleanly: %s", close_exc)
            return self
        self._stack = stack
        return self

    @staticmethod
    def _handler() -> Any:
        """
        Build the LangGraph callback handler of the SDK.

        :returns handler: A `langfuse.langchain.CallbackHandler` bound to this project's keys.
        :raises ImportError: When `langfuse` or `langchain` is not installed.
        """
        from langfuse.langchain import CallbackHandler

        return CallbackHandler(public_key=config.langfuse_public_key())

    def update(self, **fields: Any) -> None:
        """
        Add output, metadata or a level to the observation.

        :param fields: Fields of `LangfuseSpan.update`, such as `output`, `metadata`, `level`.
        """
        if self._observation is None:
            return
        try:
            self._observation.update(**fields)
        except Exception as exc:
            logger.warning("Langfuse trace could not be updated: %s", exc)

    def __exit__(self, *exc_info: Any) -> None:
        """
        Close the observation; an exception of the block is never swallowed.

        :param exc_info: The exception of the block, if any.
        """
        if self._stack is not None:
            try:
                self._stack.__exit__(*exc_info)
            except Exception as exc:
                logger.warning("Langfuse trace did not close cleanly: %s", exc)
            self._stack = None
            self._observation = None


def agent_run(park_id: str, input: Any = None) -> Trace:
    """
    Open the root trace of one run of the agent on a park.

    :param park_id: The park being swept; becomes a tag and metadata of the trace.
    :param input: What the run received.

    :returns trace: A `Trace` whose `config` carries the LangGraph callback handler.
    """
    return Trace(
        "park-dispatch",
        input=input,
        tags=[f"park:{park_id}"],
        metadata={"park_id": str(park_id)},
        callbacks=True,
    )


def model_call(name: str, input: Any = None) -> Trace:
    """
    Open the trace of one question to the decision model.

    :param name: Name of the observation, such as `jev.repair_plan`.
    :param input: The options and state sent to the model.

    :returns trace: A `Trace` whose duration is the model's latency.
    """
    return Trace(name, input=input)


def flush() -> None:
    """
    Send what is still buffered, so a short run does not end before its trace is out.

    Does nothing when tracing is off; an SDK error is logged, not raised.
    """
    client = get_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        logger.warning("Langfuse flush failed: %s", exc)


__all__ = [
    "Trace",
    "agent_run",
    "flush",
    "get_langfuse",
    "mask_sensitive",
    "model_call",
    "register_sensitive",
]
