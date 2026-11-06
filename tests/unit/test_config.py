"""The environment accessors: defaults, overrides, and values read at call time."""

from collections.abc import Callable

import pytest

from smarthack import config


def test_app_env_defaults_to_development() -> None:
    """With nothing set, the application runs as in development."""
    assert config.app_env() == config.DEFAULT_APP_ENV == "development"


def test_app_env_is_read_from_the_environment_and_lower_cased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value typed by hand into `.env` is stripped and lower-cased."""
    monkeypatch.setenv("APP_ENV", "  Production ")

    assert config.app_env() == "production"


def test_log_level_defaults_to_info() -> None:
    """With nothing set, logging is at INFO."""
    assert config.log_level() == config.DEFAULT_LOG_LEVEL == "INFO"


def test_log_level_is_upper_cased(monkeypatch: pytest.MonkeyPatch) -> None:
    """`debug` in a `.env` file means `DEBUG`."""
    monkeypatch.setenv("LOG_LEVEL", " debug ")

    assert config.log_level() == "DEBUG"


@pytest.mark.parametrize(
    "accessor, name, default",
    [
        (config.app_env, "APP_ENV", "development"),
        (config.log_level, "LOG_LEVEL", "INFO"),
    ],
)
def test_an_empty_variable_means_unset(
    monkeypatch: pytest.MonkeyPatch, accessor: Callable[[], str], name: str, default: str
) -> None:
    """`NAME=` in a `.env` file is the same as not setting it."""
    monkeypatch.setenv(name, "")

    assert accessor() == default


def test_values_are_read_on_every_call_not_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting a variable after the package was imported changes the next answer."""
    before = config.log_level()
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    assert before == "INFO"
    assert config.log_level() == "ERROR"
