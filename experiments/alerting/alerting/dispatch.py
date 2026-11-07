"""
# Dispatch

`dispatch(alert, decision)` carries out a decision already made: the email always goes out,
and when the channel is `email_si_apel` on-call is also phoned, with escalation. It returns a
JSON-ready summary (what was sent, to whom, with what status), so a LangGraph node can call it
and put the result in its state; `langgraph_node` builds such a node.

Rules enforced here, on top of the ones in `mailer`, `caller` and `escalation`:
- the decision must be for this alert (`alert_id` equal);
- an alert is dispatched at most once: it is marked in `state/alerts.json` before anything is
  sent, so a crash midway never leads to a second email or call on a re-run (at-most-once);
- with `DRY_RUN` (the default) nothing is sent and nothing is marked, so a dry run can be
  repeated.

Contacts in the summary are masked. Escalation waits between calls, so `dispatch` can block
for `ESCALATION_RETRY_MINUTES` per retry.

The following can be imported from this module:
- `dispatch`
- `langgraph_node`
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
import logging
import time
from typing import Any

from alerting import config
from alerting.caller import CallProvider
from alerting.escalation import escalate
from alerting.mailer import send_alert_email
from alerting.models import Alert, Case, Decision
from alerting.oncall import OnCallPerson, load_oncall
from alerting.spoken import call_text
from alerting.state import StateStore

__all__ = ["dispatch", "langgraph_node"]

logger = logging.getLogger(__name__)


def _case(alert: Alert | Mapping[str, Any], decision: Decision | Mapping[str, Any]) -> Case:
    alert_data = alert.model_dump() if isinstance(alert, Alert) else alert
    decision_data = decision.model_dump() if isinstance(decision, Decision) else decision
    return Case.model_validate({"alert": alert_data, "decision": decision_data})


def dispatch(
    alert: Alert | Mapping[str, Any],
    decision: Decision | Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    people: Sequence[OnCallPerson] | None = None,
    provider: CallProvider | None = None,
    store: StateStore | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """
    Send the alert email and, if the decision asks for it, phone on-call with escalation.

    :param alert: The alert, as a model or a plain dict (e.g. from LangGraph state).
    :param decision: The decision for it, as a model or a plain dict.
    :param env: Variables to read. Defaults to None, meaning the environment and `.env`.
    :param people: On-call people in escalation order. Defaults to None, meaning `oncall.json`.
    :param provider: Who places calls. Defaults to None, meaning the `CALL_PROVIDER`.
    :param store: Dispatch and call records. Defaults to None, meaning `state/alerts.json`.
    :param sleep: The sleep function used by escalation, replaceable in tests.

    :returns: A JSON-serialisable summary: `status` (`dispatched`, `dry_run` or `duplicate`),
        the email results, and the call outcome with every attempt; contacts masked.
    :raises pydantic.ValidationError: When the inputs are invalid or the decision is for
        another alert.
    """
    case = _case(alert, decision)
    alert_id = case.alert.alert_id
    env = config.environment() if env is None else env
    store = StateStore() if store is None else store
    dry_run = config.dry_run(env)
    summary: dict[str, Any] = {
        "alert_id": alert_id,
        "severity": case.decision.severity,
        "channel": case.decision.channel,
        "overridden_by_rule": case.decision.overridden_by_rule,
        "dry_run": dry_run,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    if store.is_dispatched(alert_id):
        previous = store.record(alert_id)
        logger.warning("alert %s already dispatched at %s", alert_id, previous["dispatched_at"])
        return summary | {
            "status": "duplicate",
            "previously_dispatched_at": previous["dispatched_at"],
            "previous_summary": previous["summary"],
        }
    if not dry_run:
        store.mark_dispatched(alert_id, {"status": "in_progress"})

    people = list(load_oncall(env=env).people if people is None else people)
    emails = send_alert_email(case.alert, case.decision, [p.email for p in people], env=env)
    summary["email"] = [asdict(result) for result in emails]

    call: dict[str, Any] = {"requested": case.decision.wants_call}
    if case.decision.wants_call:
        outcome = escalate(
            alert_id,
            call_text(case.alert, case.decision),
            people,
            env=env,
            provider=provider,
            store=store,
            sleep=sleep,
        )
        call |= {
            "stopped": outcome.stopped,
            "answered": outcome.answered,
            "answered_by_person": outcome.answered_by_person,
            "attempts": [
                {"person": a.person, "try": a.try_number}
                | asdict(a.result)
                | {"answered": a.result.answered}
                for a in outcome.attempts
            ],
        }
    summary["call"] = call
    summary["status"] = "dry_run" if dry_run else "dispatched"

    if not dry_run:
        store.mark_dispatched(alert_id, summary)
    logger.info(
        "alert %s: %s, emails %s, call %s",
        alert_id,
        summary["status"],
        [result.status for result in emails],
        call.get("stopped", "not requested"),
    )
    return summary


def langgraph_node(
    alert_key: str = "alert", decision_key: str = "decision", output_key: str = "dispatch"
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """
    A LangGraph node function: reads the alert and decision from state, returns the summary.

    Usage: `graph.add_node("alerting", langgraph_node())`. LangGraph is not imported here;
    the node is a plain function of the state.

    :param alert_key: State key holding the alert (model or dict).
    :param decision_key: State key holding the decision (model or dict).
    :param output_key: State key the summary is written to.

    :returns: The node function.
    """

    def node(state: Mapping[str, Any]) -> dict[str, Any]:
        return {output_key: dispatch(state[alert_key], state[decision_key])}

    return node
