"""
# Voice notification client

Text-to-speech voice call dispatch client for critical maintenance alerts.

The following can be imported from this module:
- `VoiceNotificationClient`
- `get_default_voice_client`
"""

from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)


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
    ) -> dict[str, Any]:
        """
        Trigger an automated text-to-speech emergency phone call to the crew lead.

        :param phone_number: Destination phone number.
        :param crew_name: Name of the recipient crew or team lead.
        :param turbine_id: Asset identifier of the failing turbine.
        :param park_id: Wind park identifier containing the asset.
        :param message: Voice transcript message to synthesize and speak.
        :param lead_time_hours: Estimated hours before catastrophic failure.

        :returns record: Confirmation record containing call metadata and delivery status.
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
