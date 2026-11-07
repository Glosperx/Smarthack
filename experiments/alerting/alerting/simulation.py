"""
# Simulated calls

A call provider that phones nobody: each call ends with the next outcome from a script, so
escalation can be exercised with no-answer, busy, a machine or a person answering, without
spending a real call.

Outcomes are written `status` or `status:answered_by`, for example `no-answer`, `busy`,
`completed:human`, `completed:machine_start`, `completed:unknown`, `failed`. When the
script runs out, every further call ends `no-answer`.

The following can be imported from this module:
- `SimulatedProvider`
- `parse_outcomes`
"""

from alerting.caller import CallProgress

__all__ = ["SimulatedProvider", "parse_outcomes"]


def parse_outcomes(script: str) -> list[CallProgress]:
    """
    Read a comma-separated outcome script.

    :param script: For example "no-answer,busy,completed:human".

    :returns: One outcome per call, in order.
    :raises ValueError: When a status is not a final call status.
    """
    outcomes: list[CallProgress] = []
    for item in (part.strip() for part in script.split(",") if part.strip()):
        status, _, answered_by = item.partition(":")
        if status not in {"completed", "busy", "no-answer", "failed", "canceled"}:
            raise ValueError(f"unknown simulated status {status!r}")
        duration = 25 if status == "completed" else 0
        outcomes.append(CallProgress(status, answered_by or None, duration, "simulated"))
    return outcomes


class SimulatedProvider:
    """Ends each call with the next scripted outcome; nobody is phoned."""

    name = "simulated"

    def __init__(self, outcomes: list[CallProgress]) -> None:
        """
        :param outcomes: One final outcome per call, in order.
        """
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []

    def describe(self) -> str:
        """
        :returns: A note that the calls are simulated.
        """
        return "simulated provider, nobody is phoned"

    def start(self, to: str, text: str) -> tuple[str, str]:
        """
        Pretend to place a call.

        :param to: The number.
        :param text: The message.

        :returns: A fake call id and `queued`.
        """
        self.calls.append((to, text))
        return f"SIM{len(self.calls)}", "queued"

    def poll(self, call_id: str) -> CallProgress:
        """
        End the call with its scripted outcome.

        :param call_id: The fake call id, `SIM<n>` for the n-th call.

        :returns: The n-th outcome, or `no-answer` past the end of the script.
        """
        index = int(call_id.removeprefix("SIM")) - 1
        if index < len(self.outcomes):
            return self.outcomes[index]
        return CallProgress("no-answer", None, 0, "simulated, script exhausted")
