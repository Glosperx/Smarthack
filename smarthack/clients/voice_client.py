"""
# Voice notification client

Text-to-speech voice call dispatch client for critical maintenance alerts.

By default a call is only recorded and logged: nobody is phoned. With `VOICE_CALLS_ENABLED`
the client also hands the alert to the alerting module (`experiments/alerting`), which emails
and phones the on-call person through Twilio or Infobip and applies its own gates: the
`ALLOWED_PHONES` allowlist, `DRY_RUN`, at most one dispatch per alert and three calls per
alert. Who is phoned is the on-call rotation of that module, not the crew's number: the crew
numbers of the dispatch agent are placeholders.

A failure of the real call never raises: the record says `real_call.status = "error"`, so one
bad provider cannot stop the agent's sweep.

The following can be imported from this module:
- `VoiceNotificationClient`
- `get_default_voice_client`
"""

from datetime import datetime, timedelta, timezone
import logging
import sys
from typing import Any

from smarthack import config

logger = logging.getLogger(__name__)

#: How long the maintenance window the alerting module speaks about lasts, in hours.
_WINDOW_HOURS = 10.0


def _place_real_call(
    turbine_id: int,
    park_id: str,
    lead_time_hours: float | None,
    fault_probability: float | None,
) -> dict[str, Any]:
    """
    Hand a CRITICAL alert to the alerting module, which emails and phones on-call.

    :param turbine_id: The failing turbine.
    :param park_id: The turbine's park.
    :param lead_time_hours: Hours to the predicted failure, if known.
    :param fault_probability: The model's failure probability, if known.

    :returns outcome: The alerting summary's `status` (`dispatched`, `dry_run`, `duplicate`)
        with its `alert_id`, `call` and `email`, or `status` `error` with the reason.
    """
    try:
        # The module is a standalone project next to the package, not installed: it is put on
        # the import path only when calls are on. It needs the `calls` extra (twilio, jinja2).
        folder = str(config.alerting_dir())
        if folder not in sys.path:
            sys.path.insert(0, folder)
        from alerting.config import environment
        from alerting.dispatch import dispatch

        now = datetime.now(timezone.utc)
        hours = float(lead_time_hours) if lead_time_hours is not None else 24.0
        probability = min(max(float(fault_probability or 0.0), 0.0), 1.0)
        # One alert per turbine per minute: a second watcher, or a file handled twice at
        # once, reaches the same id and the module refuses it as already dispatched.
        alert_id = f"SMH-{now:%Y%m%dT%H%M}-{park_id}-T{turbine_id}"
        alert = {
            "alert_id": alert_id,
            "park": str(park_id),
            "turbines": [{"turbine_id": f"T{int(turbine_id)}", "probability": probability}],
            "window_start": now.isoformat(),
            "window_end": (now + timedelta(hours=_WINDOW_HOURS)).isoformat(),
            "hours_to_failure": max(hours, 0.0),
            "estimated_loss_ron": 0.0,
            "created_at": now.isoformat(),
        }
        decision = {
            "alert_id": alert_id,
            "severity": "critica",
            "channel": "email_si_apel",
            "probabilities": {"critica": 1.0},
            "confidence": 1.0,
            "overridden_by_rule": "agent_critical_health_status",
        }
        # The pipeline rings once: nobody is called again when the call is not answered.
        summary = dispatch(alert, decision, env=environment() | {"CALL_RETRIES_PER_PERSON": "0"})
    except Exception as exc:  # the sweep must go on whatever the provider does
        logger.exception("real voice call for turbine %s failed", turbine_id)
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    logger.warning(
        "REAL CALL via alerting: alert=%s status=%s call=%s",
        summary.get("alert_id"),
        summary.get("status"),
        summary.get("call", {}).get("stopped"),
    )
    return {
        "status": summary.get("status"),
        "alert_id": summary.get("alert_id"),
        "call": summary.get("call"),
        "email": summary.get("email"),
    }


class VoiceNotificationClient:
    """
    Client for dispatching emergency voice calls via text-to-speech (TTS) services.

    Simulates or executes automated phone calls to wind park maintenance leads for
    critical, imminent component failures.
    """

    def __init__(self) -> None:
        """
        Initialize the voice notification client with an in-memory dispatch history.
        """
        self._history: list[dict[str, Any]] = []

    def dispatch_emergency_call(
        self,
        phone_number: str,
        crew_name: str,
        turbine_id: int,
        park_id: str,
        message: str,
        lead_time_hours: float | None = None,
        fault_probability: float | None = None,
    ) -> dict[str, Any]:
        """
        Trigger an automated text-to-speech emergency phone call to the crew lead.

        The call is always recorded and logged. With `VOICE_CALLS_ENABLED` it is also placed
        for real through the alerting module, and its outcome is in `real_call`.

        :param phone_number: Destination phone number.
        :param crew_name: Name of the recipient crew or team lead.
        :param turbine_id: Asset identifier of the failing turbine.
        :param park_id: Wind park identifier containing the asset.
        :param message: Voice transcript message to synthesize and speak.
        :param lead_time_hours: Estimated hours before catastrophic failure.
        :param fault_probability: The model's failure probability, spoken in the real call.

        :returns record: Confirmation record containing call metadata and delivery status;
            `real_call` is present only when real calls are enabled.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        call_id = f"call_{len(self._history) + 1:04d}_{turbine_id}"

        formatted_speech = (
            f"URGENT DISPATCH ALERT for {crew_name}. "
            f"Turbine {turbine_id} in {park_id} has entered CRITICAL condition. "
            f"{message} "
            f"Immediate physical intervention required."
        )

        record: dict[str, Any] = {
            "call_id": call_id,
            "timestamp": timestamp,
            "phone_number": phone_number,
            "crew_name": crew_name,
            "turbine_id": turbine_id,
            "park_id": park_id,
            "synthesized_speech": formatted_speech,
            "lead_time_hours": lead_time_hours,
            "status": "COMPLETED",
        }

        if config.voice_calls_enabled():
            record["real_call"] = _place_real_call(
                turbine_id, park_id, lead_time_hours, fault_probability
            )

        self._history.append(record)
        logger.warning(
            "EMERGENCY VOICE CALL DISPATCHED [%s] -> %s (%s) for Turbine %s in %s: %s",
            call_id,
            crew_name,
            phone_number,
            turbine_id,
            park_id,
            formatted_speech,
        )
        return record

    def get_call_history(self) -> list[dict[str, Any]]:
        """
        Retrieve all recorded voice call dispatches.

        :returns history: List of call records in chronological order.
        """
        return list(self._history)

    def clear_history(self) -> None:
        """
        Clear the call history.
        """
        self._history.clear()


_GLOBAL_VOICE_CLIENT: VoiceNotificationClient | None = None


def get_default_voice_client() -> VoiceNotificationClient:
    """
    Return or initialize the singleton default VoiceNotificationClient instance.

    :returns client: Active VoiceNotificationClient instance.
    """
    global _GLOBAL_VOICE_CLIENT
    if _GLOBAL_VOICE_CLIENT is None:
        _GLOBAL_VOICE_CLIENT = VoiceNotificationClient()
    return _GLOBAL_VOICE_CLIENT


__all__ = ["VoiceNotificationClient", "get_default_voice_client"]
