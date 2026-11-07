"""
# Local alert state

What was already done for each `alert_id`, kept in `state/alerts.json`. Two rules rest on it:
an alert is never dispatched twice, and no alert gets more than `MAX_CALLS_PER_ALERT` calls.

A call is recorded as soon as Twilio accepts it, before anyone answers, so a crash while
waiting still counts it. Writes go to a temporary file renamed over the old one, so the file
is never half-written. Contacts are stored masked.

The following can be imported from this module:
- `MAX_CALLS_PER_ALERT`
- `STATE_FILE`
- `StateStore`
"""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from alerting.config import PACKAGE_ROOT

__all__ = ["MAX_CALLS_PER_ALERT", "STATE_FILE", "StateStore"]

MAX_CALLS_PER_ALERT = 3
STATE_FILE = PACKAGE_ROOT / "state" / "alerts.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StateStore:
    """A small JSON file of per-alert records."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        """
        Use the given file; it is created on the first write.

        :param path: The JSON file. Defaults to `state/alerts.json`.
        """
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temporary, self.path)

    def record(self, alert_id: str) -> dict[str, Any]:
        """
        Everything stored for one alert.

        :param alert_id: The alert.

        :returns: A copy with `dispatched_at` (None until dispatched), `summary` and `calls`.
        """
        empty: dict[str, Any] = {"dispatched_at": None, "summary": None, "calls": []}
        return empty | self._load().get(alert_id, {})

    def calls_made(self, alert_id: str) -> int:
        """
        How many calls Twilio accepted for this alert.

        :param alert_id: The alert.

        :returns: The count.
        """
        return len(self.record(alert_id)["calls"])

    def add_call(self, alert_id: str, sid: str, recipient: str, status: str) -> None:
        """
        Record a call Twilio accepted.

        :param alert_id: The alert.
        :param sid: Twilio's call SID.
        :param recipient: The masked number.
        :param status: The status Twilio returned on creation.
        """
        data = self._load()
        entry = data.setdefault(alert_id, {"dispatched_at": None, "summary": None, "calls": []})
        entry["calls"].append(
            {"sid": sid, "recipient": recipient, "status": status, "created_at": _now()}
        )
        self._save(data)

    def update_call(self, alert_id: str, sid: str, **fields: Any) -> None:
        """
        Store the outcome of a call, e.g. its final status and `answered_by`.

        :param alert_id: The alert.
        :param sid: Twilio's call SID.
        :param fields: Values to set on that call's record.
        """
        data = self._load()
        for call in data.get(alert_id, {}).get("calls", []):
            if call["sid"] == sid:
                call.update(fields)
        self._save(data)

    def is_dispatched(self, alert_id: str) -> bool:
        """
        Whether this alert was already dispatched.

        :param alert_id: The alert.

        :returns: True once `mark_dispatched` ran for it.
        """
        return self.record(alert_id)["dispatched_at"] is not None

    def mark_dispatched(self, alert_id: str, summary: dict[str, Any]) -> None:
        """
        Remember that this alert was dispatched, with what happened.

        :param alert_id: The alert.
        :param summary: The dispatch summary, contacts masked.
        """
        data = self._load()
        entry = data.setdefault(alert_id, {"dispatched_at": None, "summary": None, "calls": []})
        entry["dispatched_at"] = _now()
        entry["summary"] = summary
        self._save(data)
