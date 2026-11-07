"""
# Spoken message

The text read to on-call over the phone, rendered from `templates/call.txt.j2`.

Numbers are written out as words, because a speech engine reading digits gets Romanian
gender wrong ("2 ore" read as "doi ore"): hours and days are feminine ("două ore",
"douăzeci și două de ore"), a turbine number is a label and keeps the masculine form
("turbina doi"). Past three turbines only the riskiest is named, and the whole message is
refused above `MAX_WORDS` words, so it stays short enough to understand on a phone line.

The following can be imported from this module:
- `MAX_WORDS`
- `call_text`
- `number_words`
- `spoken_eta`
- `spoken_turbines`
- `word_count`
"""

import math
import re

from alerting.models import Alert, Decision
from alerting.templates import render
from alerting.wording import SEVERITY, needs_de

__all__ = [
    "MAX_WORDS",
    "call_text",
    "number_words",
    "spoken_eta",
    "spoken_turbines",
    "word_count",
]

MAX_WORDS = 40

_MAX_NAMED_TURBINES = 3
_HOURS_BEFORE_DAYS = 48

_UNITS = ["zero", "unu", "doi", "trei", "patru", "cinci", "șase", "șapte", "opt", "nouă"]
_UNITS_FEMININE = {1: "una", 2: "două"}
_TEENS = [
    "zece",
    "unsprezece",
    "doisprezece",
    "treisprezece",
    "paisprezece",
    "cincisprezece",
    "șaisprezece",
    "șaptesprezece",
    "optsprezece",
    "nouăsprezece",
]
_TENS = ["", "", "douăzeci", "treizeci", "patruzeci", "cincizeci", "șaizeci", "șaptezeci"]
_TENS += ["optzeci", "nouăzeci"]


def number_words(number: int, feminine: bool = False) -> str:
    """
    Write a whole number from 0 to 999 999 in Romanian words.

    :param number: The number.
    :param feminine: Whether it counts a feminine noun ("două ore", not "doi ore").

    :returns: For example "douăzeci și două" or "o sută cinci".
    :raises ValueError: When the number is negative or above 999 999.
    """
    if not 0 <= number <= 999_999:
        raise ValueError("number_words handles 0 to 999 999")
    if number >= 1000:
        thousands, rest = divmod(number, 1000)
        head = "o mie" if thousands == 1 else _feminine_count(thousands, "o mie", "mii")
        return head if rest == 0 else f"{head} {number_words(rest, feminine)}"
    if number >= 100:
        hundreds, rest = divmod(number, 100)
        head = "o sută" if hundreds == 1 else f"{number_words(hundreds, feminine=True)} sute"
        return head if rest == 0 else f"{head} {number_words(rest, feminine)}"
    if number >= 20:
        tens, unit = divmod(number, 10)
        return _TENS[tens] if unit == 0 else f"{_TENS[tens]} și {number_words(unit, feminine)}"
    if number >= 10:
        return "douăsprezece" if number == 12 and feminine else _TEENS[number - 10]
    return _UNITS_FEMININE.get(number, _UNITS[number]) if feminine else _UNITS[number]


def _feminine_count(number: int, one: str, many: str) -> str:
    if number == 1:
        return one
    return f"{number_words(number, feminine=True)} {'de ' if needs_de(number) else ''}{many}"


def spoken_eta(hours: float) -> str:
    """
    Time to failure as said aloud, rounded down like the email.

    :param hours: Estimated hours until the failure.

    :returns: "aproximativ optsprezece ore", "aproximativ o oră", "aproximativ patru zile",
        "mai puțin de o oră".
    """
    if hours < 1:
        return "mai puțin de o oră"
    if hours >= _HOURS_BEFORE_DAYS:
        return f"aproximativ {_feminine_count(math.floor(hours / 24), 'o zi', 'zile')}"
    return f"aproximativ {_feminine_count(math.floor(hours), 'o oră', 'ore')}"


def spoken_turbines(numbers: list[int]) -> tuple[str, bool]:
    """
    Name the turbines as said aloud, the riskiest first.

    :param numbers: Turbine numbers, the riskiest first.

    :returns: The phrase and whether it is plural: ("turbina șapte", False),
        ("turbinele unsprezece și doisprezece", True), or past three turbines
        ("turbina unsprezece și încă patru turbine", True).
    """
    words = [number_words(number) for number in numbers]
    if len(words) == 1:
        return f"turbina {words[0]}", False
    if len(words) > _MAX_NAMED_TURBINES:
        others = _feminine_count(len(words) - 1, "o turbină", "turbine")
        return f"turbina {words[0]} și încă {others}", True
    return f"turbinele {', '.join(words[:-1])} și {words[-1]}", True


def word_count(text: str) -> int:
    """
    Count the words a listener hears; "e-mailul" is one word.

    :param text: The message.

    :returns: The number of words.
    """
    return len(re.findall(r"[\w-]+", text))


def call_text(alert: Alert, decision: Decision) -> str:
    """
    Render the message read during the call.

    :param alert: The alert.
    :param decision: The decision made for it.

    :returns: The message, one line.
    :raises ValueError: When it is longer than `MAX_WORDS` words.
    """
    turbines, plural = spoken_turbines([t.number for t in alert.turbines_by_risk])
    text = render(
        "call.txt.j2",
        park=alert.park,
        turbines=turbines,
        plural=plural,
        risk=SEVERITY[decision.severity].risk,
        eta=spoken_eta(alert.hours_to_failure),
    )
    text = " ".join(text.split())
    if word_count(text) > MAX_WORDS:
        raise ValueError(f"spoken message has {word_count(text)} words, over {MAX_WORDS}")
    return text
