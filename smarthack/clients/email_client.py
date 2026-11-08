"""
# Email notification client

Email ticketing and maintenance dispatch client for warning and watch alerts.

By default a ticket is only recorded and logged: nothing is sent. With `REAL_EMAILS_ENABLED` an
email-only alert (`real_alert` given) is also handed to the alerting module
(`experiments/alerting`), which sends it through its mail backend and applies its own gates:
the `ALLOWED_EMAILS` allowlist, `DRY_RUN` and at most one dispatch per alert. It is addressed to
that module's on-call rotation, not to the crew's address, and the decision it receives is
`doar_email`, so nobody is phoned. A failure never raises: the record says
`real_email.status = "error"`.

The following can be imported from this module:
- `EmailNotificationClient`
- `get_default_email_client`
"""

from datetime import datetime, timedelta, timezone
import logging
import sys
from typing import Any

from smarthack import config
from smarthack.clients.supabase import park_display_name

logger = logging.getLogger(__name__)

#: How long the maintenance window the alerting module writes about lasts, in hours.
_WINDOW_HOURS = 10.0


def _send_real_email(turbine_id: int, park_id: str, real_alert: dict[str, Any]) -> dict[str, Any]:
    """
    Hand an email-only alert to the alerting module, which emails on-call and never phones.

    :param turbine_id: The turbine the alert is about.
    :param park_id: The turbine's park.
    :param real_alert: `health_status`, `lead_time_hours` and `fault_probability` of the turbine;
        any may be missing.

    :returns outcome: The alerting summary's `status` (`dispatched`, `dry_run`, `duplicate`)
        with its `alert_id` and `email`, or `status` `error` with the reason.
    """
    try:
        # The module is a standalone project next to the package, not installed: it is put on
        # the import path only when real emails are on. It needs the `calls` extra (jinja2).
        folder = str(config.alerting_dir())
        if folder not in sys.path:
            sys.path.insert(0, folder)
        from alerting.config import environment
        from alerting.dispatch import dispatch

        now = datetime.now(timezone.utc)
        hours = real_alert.get("lead_time_hours")
        hours = float(hours) if hours is not None else 24.0 * 7
        probability = min(max(float(real_alert.get("fault_probability") or 0.0), 0.0), 1.0)
        severity = (
            "medie" if str(real_alert.get("health_status", "")).upper() == "WARNING" else "scazuta"
        )
        # One alert per turbine per minute: the same file handled twice reaches the same id and
        # the module refuses it as already dispatched.
        alert_id = f"SMH-{now:%Y%m%dT%H%M}-{park_id}-T{turbine_id}"
        alert = {
            "alert_id": alert_id,
            "park": park_display_name(park_id),
            "turbines": [{"turbine_id": f"T{int(turbine_id):02d}", "probability": probability}],
            "window_start": now.isoformat(),
            "window_end": (now + timedelta(hours=_WINDOW_HOURS)).isoformat(),
            "hours_to_failure": max(hours, 0.0),
            "estimated_loss_ron": 0.0,
            "created_at": now.isoformat(),
        }
        decision = {
            "alert_id": alert_id,
            "severity": severity,
            "channel": "doar_email",
            "probabilities": {severity: 1.0},
            "confidence": 1.0,
            "overridden_by_rule": "agent_email_only_channel",
        }
        summary = dispatch(alert, decision, env=environment())
    except Exception as exc:  # the sweep must go on whatever the mail backend does
        logger.exception("real email for turbine %s failed", turbine_id)
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    logger.warning(
        "REAL EMAIL via alerting: alert=%s status=%s",
        summary.get("alert_id"),
        summary.get("status"),
    )
    return {
        "status": summary.get("status"),
        "alert_id": summary.get("alert_id"),
        "email": summary.get("email"),
    }


class EmailNotificationClient:
    """
    Client for dispatching maintenance work order tickets via email.

    Dispatches detailed maintenance tickets including diagnostic telemetry,
    subsystem risk breakdown, and recommended protocols for non-critical warnings.
    """

    def __init__(self) -> None:
        """
        Initialize the email notification client with an in-memory dispatch history.
        """
        self._history: list[dict[str, Any]] = []

    def dispatch_work_ticket(
        self,
        recipient_email: str,
        crew_name: str,
        turbine_id: int,
        park_id: str,
        subject: str,
        body: str,
        diagnostics: dict[str, Any] | None = None,
        real_alert: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Dispatch a maintenance work ticket email to the park maintenance team.

        :param recipient_email: Recipient email address.
        :param crew_name: Name of the assigned maintenance crew.
        :param turbine_id: Asset identifier of the turbine needing attention.
        :param park_id: Wind park identifier.
        :param subject: Email subject line.
        :param body: Detailed message body describing the fault and action.
        :param diagnostics: Optional diagnostic payload and subsystem risk breakdown.
        :param real_alert: Set for an email-only alert, with `health_status`, `lead_time_hours` and
            `fault_probability`: with `REAL_EMAILS_ENABLED` the alert is also really emailed to
            on-call. Left out for the email that goes with a phone call, which the call's own
            dispatch already sends.

        :returns record: Confirmation record containing email metadata and delivery status.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        ticket_id = f"TICK-{len(self._history) + 1:04d}-{park_id[:4].upper()}"

        record: dict[str, Any] = {
            "ticket_id": ticket_id,
            "timestamp": timestamp,
            "recipient_email": recipient_email,
            "crew_name": crew_name,
            "turbine_id": turbine_id,
            "park_id": park_id,
            "subject": subject,
            "body": body,
            "diagnostics": diagnostics or {},
            "status": "DELIVERED",
        }

        if real_alert is not None and config.real_emails_enabled():
            record["real_email"] = _send_real_email(turbine_id, park_id, real_alert)

        self._history.append(record)
        logger.info(
            "MAINTENANCE EMAIL DISPATCHED [%s] -> %s (%s) for Turbine %s: %s",
            ticket_id,
            crew_name,
            recipient_email,
            turbine_id,
            subject,
        )
        return record

    def get_email_history(self) -> list[dict[str, Any]]:
        """
        Retrieve all recorded email dispatches.

        :returns history: List of email records in chronological order.
        """
        return list(self._history)

    def clear_history(self) -> None:
        """
        Clear the email dispatch history.
        """
        self._history.clear()


_GLOBAL_EMAIL_CLIENT: EmailNotificationClient | None = None


def get_default_email_client() -> EmailNotificationClient:
    """
    Return or initialize the singleton default EmailNotificationClient instance.

    :returns client: Active EmailNotificationClient instance.
    """
    global _GLOBAL_EMAIL_CLIENT
    if _GLOBAL_EMAIL_CLIENT is None:
        _GLOBAL_EMAIL_CLIENT = EmailNotificationClient()
    return _GLOBAL_EMAIL_CLIENT


__all__ = ["EmailNotificationClient", "get_default_email_client"]
