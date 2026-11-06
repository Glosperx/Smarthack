"""
# Config

The **only** module that reads `os.environ`. Everything else imports these
accessors, never the environment directly, so that there is a single place to
look when asking "where does this setting come from?". `.env.example` lists every
variable read here, and `tests/unit/test_repository_files.py` keeps the two in step.

Values are read on every call rather than snapshotted at import time. That keeps
the module honest under tests, which set environment variables after the package
has already been imported.

Cloud clients belong here too, when the project grows any: each initialisation
sits in its own `try/except` that leaves `None` behind on failure, so importing
the package works with no credentials present and no newcomer is blocked from
running the tests. Nothing is stubbed out in advance.

The following can be imported from this module:
- `app_env`
- `log_level`
- `DEFAULT_APP_ENV`
- `DEFAULT_LOG_LEVEL`
"""

import os
from pathlib import Path

from dotenv import load_dotenv

#: The environment the application runs in when `APP_ENV` is not set.
DEFAULT_APP_ENV = "development"

#: The logging level when `LOG_LEVEL` is not set.
DEFAULT_LOG_LEVEL = "INFO"

# `load_dotenv()` looks for `.env` upward from this file in a script, but upward from the working
# directory in a notebook or a REPL: a kernel started outside the repository then found none and a
# setting was silently missing. The repository's own comes second. A variable already set, by the
# environment or by the first file, is never overwritten.
load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def app_env() -> str:
    """
    Return the environment the application runs in.

    :returns name: The configured name, lower-cased, such as `"development"`,
        `"staging"` or `"production"`. Defaults to `"development"`.
    """
    return (os.environ.get("APP_ENV") or DEFAULT_APP_ENV).strip().lower()


def log_level() -> str:
    """
    Return the configured logging level name.

    :returns level: An upper-case level name. Defaults to `"INFO"`.
    """
    return (os.environ.get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()


__all__ = ["app_env", "log_level", "DEFAULT_APP_ENV", "DEFAULT_LOG_LEVEL"]
