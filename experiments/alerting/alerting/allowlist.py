"""
# Recipient allowlist

The last gate before anything is sent: an email address or phone number missing from
`ALLOWED_EMAILS` / `ALLOWED_PHONES` is refused, whatever `oncall.json` says. An empty list
refuses everyone. The check runs in dry-run mode too, so a dry run shows the refusals a real
run would hit.

Error messages and printed summaries carry masked contacts only (`al***@gmail.com`,
`+407******23`).

The following can be imported from this module:
- `Allowlist`
- `RecipientNotAllowed`
- `mask_email`
- `mask_phone`
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from alerting.config import allowed_emails, allowed_phones

__all__ = ["Allowlist", "RecipientNotAllowed", "mask_email", "mask_phone"]


class RecipientNotAllowed(Exception):
    """A recipient is missing from the allowlist."""


def mask_email(address: str) -> str:
    """
    Hide most of the local part of an address.

    :param address: An email address.

    :returns: The first two characters, `***` and the domain, e.g. `al***@gmail.com`.
    """
    local, _, domain = address.strip().partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"


def mask_phone(number: str) -> str:
    """
    Hide the middle digits of a phone number.

    :param number: A phone number, in E.164 form.

    :returns: The first four and last two characters with stars between, e.g. `+407******23`.
    """
    number = number.strip()
    if len(number) <= 6:
        return "*" * len(number)
    return number[:4] + "*" * (len(number) - 6) + number[-2:]


@dataclass(frozen=True)
class Allowlist:
    """The recipients allowed by `.env`."""

    emails: frozenset[str]
    phones: frozenset[str]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        """
        Read `ALLOWED_EMAILS` and `ALLOWED_PHONES`.

        :param env: Variables to read. Defaults to None, meaning the environment and `.env`.

        :returns: The allowlist.
        """
        return cls(emails=allowed_emails(env), phones=allowed_phones(env))

    def check_email(self, address: str) -> str:
        """
        Accept an address only if it is allowed.

        :param address: The recipient's address.

        :returns: The address, stripped.
        :raises RecipientNotAllowed: When the address is not in `ALLOWED_EMAILS`.
        """
        address = address.strip()
        if address.lower() not in self.emails:
            raise RecipientNotAllowed(f"{mask_email(address)} is not in ALLOWED_EMAILS")
        return address

    def check_phone(self, number: str) -> str:
        """
        Accept a number only if it is allowed.

        :param number: The recipient's number.

        :returns: The number without spaces and dashes.
        :raises RecipientNotAllowed: When the number is not in `ALLOWED_PHONES`.
        """
        number = number.strip().replace(" ", "").replace("-", "")
        if number not in self.phones:
            raise RecipientNotAllowed(f"{mask_phone(number)} is not in ALLOWED_PHONES")
        return number
