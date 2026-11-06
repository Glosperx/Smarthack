"""
# Logging Utils

The only module that configures logging. Every other module obtains its logger
with `logging.getLogger(__name__)` and configures nothing, so importing the
package never clobbers the logging of an application embedding it.

The level comes from `smarthack.config`, never from the environment directly.

The following can be imported from this module:
- `configure_logging`
- `DEFAULT_LOG_FORMAT`
"""

import logging

from smarthack.config import log_level

_CONFIGURED = False

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: str | None = None, force: bool = False) -> None:
    """
    Configure the root logger once, for the application's entry point.

    Calling this more than once is a no-op unless `force` is set, so an entry
    point may call it defensively without overriding a configuration the
    embedding application already installed.

    :param level: Logging level name, for example `"INFO"`. Defaults to None,
        meaning take the level from the environment via `config.log_level()`.
    :param force: Whether to reconfigure even if this function already ran.
        Defaults to False, meaning the first configuration wins.

    :returns: None.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    logging.basicConfig(level=level or log_level(), format=DEFAULT_LOG_FORMAT, force=force)
    _CONFIGURED = True


__all__ = ["configure_logging", "DEFAULT_LOG_FORMAT"]
