"""
# Alert and decision models

What the alerting module receives: an `Alert` from the fault forecaster and a `Decision`
from the decision model, which has already chosen the severity and the channel. This module
only executes that decision, so both inputs are validated strictly: an unknown field, a typo
in `channel` or a naive datetime fails loudly instead of silently skipping a phone call.

A `Case` pairs the two and refuses a decision made for another alert.

The following can be imported from this module:
- `Alert`
- `Case`
- `Channel`
- `Decision`
- `Severity`
- `TurbineRisk`
- `load_case`
"""

import json
from pathlib import Path
import re
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

__all__ = ["Alert", "Case", "Channel", "Decision", "Severity", "TurbineRisk", "load_case"]

Severity = Literal["scazuta", "medie", "ridicata", "critica"]
Channel = Literal["doar_email", "email_si_apel"]

Probability = Annotated[float, Field(ge=0.0, le=1.0)]

_TURBINE_ID = re.compile(r"^[A-Za-z]*0*([1-9]\d*)$")


class _Strict(BaseModel):
    """Base for every input model: unknown fields are refused and instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TurbineRisk(_Strict):
    """One turbine at risk and the forecaster's probability that it fails."""

    turbine_id: str = Field(pattern=_TURBINE_ID.pattern, examples=["T07", "WTG3", "7"])
    probability: Probability

    @property
    def number(self) -> int:
        """
        The turbine's number, as it is said aloud.

        :returns: The trailing number of `turbine_id`, without leading zeros ("T07" gives 7).
        """
        match = _TURBINE_ID.match(self.turbine_id)
        assert match is not None  # guaranteed by the field pattern
        return int(match.group(1))


class Alert(_Strict):
    """
    A fault forecast for one park.

    `hours_to_failure` is the central estimate and `window_start`/`window_end` the probable
    window around it; all datetimes carry a timezone.
    """

    alert_id: str = Field(min_length=1)
    park: str = Field(min_length=1)
    turbines: list[TurbineRisk] = Field(min_length=1)
    window_start: AwareDatetime
    window_end: AwareDatetime
    hours_to_failure: float = Field(ge=0.0)
    estimated_loss_ron: float = Field(ge=0.0)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        numbers = [turbine.number for turbine in self.turbines]
        if len(numbers) != len(set(numbers)):
            raise ValueError("each turbine may appear only once")
        return self

    @property
    def turbines_by_risk(self) -> list[TurbineRisk]:
        """
        The turbines, the most likely to fail first.

        :returns: A new list sorted by probability, descending; ties keep the input order.
        """
        return sorted(self.turbines, key=lambda turbine: turbine.probability, reverse=True)


class Decision(_Strict):
    """
    What the decision model chose for an alert.

    `overridden_by_rule` must be present: null when the model's choice stands, or the name of
    the deterministic rule that replaced it.
    """

    alert_id: str = Field(min_length=1)
    severity: Severity
    channel: Channel
    probabilities: dict[str, Probability] = Field(min_length=1)
    confidence: Probability
    overridden_by_rule: str | None

    @property
    def wants_call(self) -> bool:
        """
        Whether on-call must also be phoned.

        :returns: True when the channel is `email_si_apel`.
        """
        return self.channel == "email_si_apel"


class Case(_Strict):
    """An alert and the decision made for it."""

    alert: Alert
    decision: Decision

    @model_validator(mode="after")
    def _check_same_alert(self) -> Self:
        if self.alert.alert_id != self.decision.alert_id:
            raise ValueError(
                f"decision is for alert {self.decision.alert_id!r}, " f"not {self.alert.alert_id!r}"
            )
        return self


def load_case(path: str | Path) -> Case:
    """
    Read an example case from a JSON file holding `{"alert": {...}, "decision": {...}}`.

    :param path: Path to the JSON file.

    :returns: The validated case.
    :raises pydantic.ValidationError: When the content does not match the models.
    """
    return Case.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
