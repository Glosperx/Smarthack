"""
# Templates

Renders the Jinja2 templates in `alerting/templates/`. Every text sent, email or spoken,
comes from a template there; Python only prepares the values. `*.html.j2` files are
HTML-escaped, the others are not, and an unknown variable is an error rather than an empty
string.

The following can be imported from this module:
- `render`
"""

from functools import cache
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

__all__ = ["render"]


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


@cache
def _environment() -> Environment:
    environment = Environment(
        loader=PackageLoader("alerting", "templates"),
        autoescape=lambda name: name is not None and name.endswith(".html.j2"),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["first_upper"] = _first_upper
    return environment


def render(name: str, **context: Any) -> str:
    """
    Render one template.

    :param name: File name inside `alerting/templates/`, e.g. `email.txt.j2`.
    :param context: The template's variables.

    :returns: The rendered text, without a trailing newline.
    :raises jinja2.UndefinedError: When the template uses a variable not in `context`.
    """
    return _environment().get_template(name).render(**context).rstrip("\n")
