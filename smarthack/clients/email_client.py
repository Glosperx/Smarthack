"""
# Email notification client

Email ticketing and maintenance dispatch client for warning and watch alerts.

The following can be imported from this module:
- `EmailNotificationClient`
- `get_default_email_client`
"""

from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)


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
