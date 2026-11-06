"""`configure_logging`: configures once, can be forced, takes its level from the environment."""

from collections.abc import Iterator
from contextlib import contextmanager
import logging

import pytest

from smarthack.utils import logging_utils
from smarthack.utils.logging_utils import configure_logging


@contextmanager
def empty_root_logger() -> Iterator[logging.Logger]:
    """
    Give the block a root logger with no handlers, and put the real one back after.

    pytest installs its own handlers on the root logger at the start of each test,
    and `basicConfig` does nothing when there are any, so without this the function
    under test would be invisible. It has to be a block inside the test rather than
    a fixture: a fixture runs before pytest adds those handlers. The module's
    "already configured" flag is reset, and restored, for the same reason.

    :returns root: The root logger, empty.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_flag = logging_utils._CONFIGURED
    root.handlers.clear()
    logging_utils._CONFIGURED = False
    try:
        yield root
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        logging_utils._CONFIGURED = saved_flag


def test_the_first_call_installs_a_handler_at_the_requested_level() -> None:
    """An explicit level wins, and a handler appears."""
    with empty_root_logger() as root:
        configure_logging(level="WARNING")

        assert len(root.handlers) == 1
        assert root.level == logging.WARNING


def test_the_level_defaults_to_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no argument, the level comes from `LOG_LEVEL` through `config`."""
    monkeypatch.setenv("LOG_LEVEL", "debug")

    with empty_root_logger() as root:
        configure_logging()

        assert root.level == logging.DEBUG


def test_a_second_call_is_a_no_op() -> None:
    """The first configuration wins, so an entry point may call this defensively."""
    with empty_root_logger() as root:
        configure_logging(level="WARNING")
        configure_logging(level="DEBUG")

        assert len(root.handlers) == 1
        assert root.level == logging.WARNING


def test_force_reconfigures_without_stacking_handlers() -> None:
    """`force=True` replaces the configuration instead of adding a second handler."""
    with empty_root_logger() as root:
        configure_logging(level="WARNING")
        configure_logging(level="DEBUG", force=True)

        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG


def test_the_format_is_the_documented_one() -> None:
    """Every record carries time, level, logger name and message."""
    with empty_root_logger() as root:
        configure_logging()

        formatter = root.handlers[0].formatter
        assert formatter is not None
        assert formatter._fmt == logging_utils.DEFAULT_LOG_FORMAT


def test_the_helper_leaves_the_real_root_logger_as_it_found_it() -> None:
    """The isolation block must not leak a handler, a level or the flag into the next test."""
    root = logging.getLogger()
    before = (root.handlers[:], root.level, logging_utils._CONFIGURED)

    with empty_root_logger():
        configure_logging(level="ERROR")

    assert (root.handlers[:], root.level, logging_utils._CONFIGURED) == before
