"""
# Escalation

Who gets phoned, in what order, until someone answers. Deterministic: the same outcomes
always produce the same calls.

For each person in `oncall.json`, in order:
1. call; if a person answers (`CallResult.answered`), stop;
2. otherwise (no answer, busy, a machine, unknown, failed) wait `ESCALATION_RETRY_MINUTES`
   (default 5) and call the same person once more;
3. still nothing: move on to the next person straight away.

It also stops early when a call is not placed at all:
- `dry_run`: the first call is shown and nothing more, since no outcome can follow;
- `limit_reached`: the alert already had `MAX_CALLS_PER_ALERT` calls;
- `refused`: that person's number is not in `ALLOWED_PHONES`, so retrying is pointless and
  the next person is tried.

With two people this is at most three calls (first, retry, second person), which is also the
per-alert cap.

Waiting blocks the caller. That is fine for a prototype run from a LangGraph node; a service
would schedule the retry instead of sleeping.

The following can be imported from this module:
- `Attempt`
- `EscalationOutcome`
- `escalate`
- `retry_delay_minutes`
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import logging
import time

from alerting import config
from alerting.caller import CallProvider, CallResult, place_call, wait_for_call
from alerting.oncall import OnCallPerson
from alerting.state import StateStore

__all__ = ["Attempt", "EscalationOutcome", "escalate", "retry_delay_minutes"]

logger = logging.getLogger(__name__)

_RETRIES_PER_PERSON = 1


@dataclass(frozen=True)
class Attempt:
    """One call in the escalation."""

    person: str
    try_number: int
    result: CallResult


@dataclass(frozen=True)
class EscalationOutcome:
    """
    How the escalation ended.

    `stopped` is `answered`, `exhausted` (everyone tried, nobody answered), `limit_reached`
    or `dry_run`.
    """

    stopped: str
    answered_by_person: str | None = None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def answered(self) -> bool:
        """
        Whether someone took a call.

        :returns: True when the escalation stopped because a person answered.
        """
        return self.stopped == "answered"


def retry_delay_minutes(env: Mapping[str, str] | None = None) -> float:
    """
    Minutes to wait before calling the same person again.

    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.

    :returns: `ESCALATION_RETRY_MINUTES`, or 5 when unset.
    :raises ValueError: When the value is negative or not a number.
    """
    env = config.environment() if env is None else env
    raw = env.get("ESCALATION_RETRY_MINUTES", "").strip() or "5"
    minutes = float(raw)
    if minutes < 0:
        raise ValueError("ESCALATION_RETRY_MINUTES must not be negative")
    return minutes


def escalate(
    alert_id: str,
    text: str,
    people: Sequence[OnCallPerson],
    env: Mapping[str, str] | None = None,
    provider: CallProvider | None = None,
    store: StateStore | None = None,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = 3.0,
) -> EscalationOutcome:
    """
    Phone on-call people in order until one answers.

    :param alert_id: The alert; the per-alert call cap applies across the whole escalation.
    :param text: The spoken message.
    :param people: On-call people, in escalation order.
    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.
    :param provider: Who places calls. Defaults to None, meaning the `CALL_PROVIDER`.
    :param store: Where calls are counted. Defaults to None, meaning `state/alerts.json`.
    :param sleep: The sleep function for the retry delay and polling, replaceable in tests.
    :param poll_seconds: Seconds between polls while a call is in progress.

    :returns: Every attempt, in order, and why the escalation stopped.
    """
    env = config.environment() if env is None else env
    store = StateStore() if store is None else store
    delay_seconds = retry_delay_minutes(env) * 60
    attempts: list[Attempt] = []
    for person in people:
        for try_number in range(1, _RETRIES_PER_PERSON + 2):
            if try_number > 1:
                logger.info("%s did not answer; calling again in %.0f s", person.id, delay_seconds)
                sleep(delay_seconds)
            placed = place_call(alert_id, person.phone, text, env, provider, store)
            result = wait_for_call(
                alert_id, placed, env, provider, store, poll_seconds=poll_seconds, sleep=sleep
            )
            attempts.append(Attempt(person.id, try_number, result))
            logger.info(
                "escalation %s: %s try %d -> %s (answered_by=%s)",
                alert_id,
                person.id,
                try_number,
                result.status,
                result.answered_by,
            )
            if result.answered:
                return EscalationOutcome("answered", person.id, attempts)
            if result.status in {"dry_run", "limit_reached"}:
                return EscalationOutcome(result.status, None, attempts)
            if result.status == "refused":
                break
    return EscalationOutcome("exhausted", None, attempts)
