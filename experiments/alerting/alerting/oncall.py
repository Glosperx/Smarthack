"""
# On-call rotation

Who is emailed and phoned, in escalation order: the first person is called first.

`oncall.json` may hold contact details literally or as `${VAR}` placeholders filled from
the environment (`.env`), which keeps phone numbers and addresses out of Git. A placeholder
that is unset or empty is an error naming the variable, never its value; validation errors
hide the input for the same reason.

The following can be imported from this module:
- `ONCALL_FILE`
- `OnCallPerson`
- `OnCallRotation`
- `load_oncall`
"""

from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alerting.config import PACKAGE_ROOT, environment

__all__ = ["ONCALL_FILE", "OnCallPerson", "OnCallRotation", "load_oncall"]

ONCALL_FILE = PACKAGE_ROOT / "oncall.json"

E164 = r"^\+[1-9]\d{7,14}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_PRIVATE = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class OnCallPerson(BaseModel):
    """One person on call. `phone` is in E.164 form, for example +40712345678."""

    model_config = _PRIVATE

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    email: str = Field(pattern=EMAIL)
    phone: str = Field(pattern=E164)


class OnCallRotation(BaseModel):
    """The people on call, in the order they are called."""

    model_config = _PRIVATE

    people: list[OnCallPerson] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Self:
        ids = [person.id for person in self.people]
        if len(ids) != len(set(ids)):
            raise ValueError("each on-call id may appear only once")
        return self


def _expand(value: Any, env: Mapping[str, str], source: Path) -> Any:
    """Replace every `${VAR}` in the strings of a parsed JSON value."""
    if isinstance(value, dict):
        return {key: _expand(item, env, source) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item, env, source) for item in value]
    if not isinstance(value, str):
        return value

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if not env.get(name, "").strip():
            raise ValueError(f"{source.name}: ${{{name}}} is not set; fill it in .env")
        return env[name].strip()

    return _PLACEHOLDER.sub(substitute, value)


def load_oncall(path: Path = ONCALL_FILE, env: Mapping[str, str] | None = None) -> OnCallRotation:
    """
    Read the on-call rotation, filling `${VAR}` placeholders.

    :param path: The rotation file. Defaults to `experiments/alerting/oncall.json`.
    :param env: Variables for the placeholders. Defaults to None, meaning `environment()`.

    :returns: The validated rotation.
    :raises ValueError: When a placeholder is unset or empty.
    :raises pydantic.ValidationError: When the content does not match the model.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return OnCallRotation.model_validate(_expand(raw, environment() if env is None else env, path))
