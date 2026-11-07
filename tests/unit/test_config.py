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
        (config.host, "SMARTHACK_HOST", "127.0.0.1"),
        (config.example_service_url, "SMARTHACK_EXAMPLE_SERVICE_URL", "http://localhost:9000"),
        (config.timezone, "SMARTHACK_TIMEZONE", "UTC"),
        (config.supabase_url, "SUPABASE_URL", ""),
        (config.supabase_key, "SUPABASE_KEY", ""),
    ],
)
def test_an_empty_variable_means_unset(
    monkeypatch: pytest.MonkeyPatch, accessor: Callable[[], str], name: str, default: str
) -> None:
    """`NAME=` in a `.env` file is the same as not setting it."""
    monkeypatch.setenv(name, "")

    assert accessor() == default


def test_numeric_and_path_accessors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Port and timeout parse numbers, directories resolve paths."""
    assert config.port() == 8000
    assert config.http_timeout() == 30.0

    monkeypatch.setenv("SMARTHACK_PORT", "9999")
    monkeypatch.setenv("SMARTHACK_HTTP_TIMEOUT", "15.5")
    assert config.port() == 9999
    assert config.http_timeout() == 15.5


def test_values_are_read_on_every_call_not_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting a variable after the package was imported changes the next answer."""
    before = config.log_level()
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    assert before == "INFO"
    assert config.log_level() == "ERROR"


def test_maintenance_directories_default_to_relative_paths() -> None:
    """Maintenance data and model accessors default to paths under data/ and models/."""
    data_path = config.maintenance_data_dir()
    models_path = config.maintenance_models_dir()

    assert data_path.name == "maintenance"
    assert models_path.name == "maintenance"
    assert "data" in str(data_path)
    assert "models" in str(models_path)


def test_timezone_accessor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timezone defaults to UTC, accepts valid IANA names, rejects invalid names."""
    assert config.timezone() == "UTC"
    monkeypatch.setenv("SMARTHACK_TIMEZONE", "Europe/Bucharest")
    assert config.timezone() == "Europe/Bucharest"

    monkeypatch.setenv("SMARTHACK_TIMEZONE", "Invalid/Timezone_Name")
    with pytest.raises(Exception):
        config.timezone()
