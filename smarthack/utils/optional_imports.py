"""
# Optional Imports

The one decision every guarded registry import has to make: is this failed
import a missing extra, or a bug in our own code?

A registry built with `try/except ImportError` is what lets a missing extra
make the registry *smaller* instead of breaking it. A bare `except ImportError:
pass` also swallows a typo in this package, though: the class quietly vanishes
from the registry and surfaces hours later as a `KeyError`. So the guard asks
which module was missing, and re-raises anything that is not a declared
optional dependency.

```python
try:
    from smarthack.storage.s3_store import S3Store
except ImportError as exc:
    skip_if_optional(exc, "S3Store", ("boto3", "botocore"))
else:
    STORES["s3"] = S3Store
```

**Each caller declares its own optional modules.** The list sits next to the
guarded imports it describes, so a new extra costs a line there and none here.

**What counts as missing is only a missing module.** An extra that is installed
but cannot load — a native library whose runtime is absent, say — raises
something other than `ImportError`, and that is left to propagate with the
library's own message. A registry that shrinks is a supported state; an
installation that is broken is not, and hiding it behind "not installed" would
send whoever reads the warning to install what is already there.

The following can be imported from this module:
- `skip_if_optional`
"""

from collections.abc import Iterable
import logging

logger = logging.getLogger(__name__)


def skip_if_optional(
    exc: ImportError, what: str, optional_modules: Iterable[str], warn: bool = True
) -> None:
    """
    Decide whether a failed import is a missing extra or a real bug.

    Returns quietly when it is a missing extra, so the caller's registry simply
    goes without the entry. The module that was missing is compared by its
    top-level package, so `botocore.exceptions` counts as `botocore`.

    :param exc: The import error that was raised.
    :param what: What could not be registered, for the log message, such as
        `"S3Store"`.
    :param optional_modules: The top-level module names the caller declares
        optional, such as `("boto3", "botocore")`.
    :param warn: Whether to log a warning naming what is missing. Defaults to
        True. A package `__init__.py` that re-exports the same class the registry
        registers passes False, so one missing extra is reported once.

    :returns: None, when the missing module is a declared optional one.

    :raises ImportError: Re-raised unchanged when the missing module is not a
        declared optional dependency — that is our own broken code, and it must
        never be mistaken for an uninstalled extra.
    """
    if exc.name is None or exc.name.split(".")[0] not in set(optional_modules):
        raise exc
    if warn:
        logger.warning(
            "not registering %s: optional dependency %r is not installed", what, exc.name
        )


__all__ = ["skip_if_optional"]
