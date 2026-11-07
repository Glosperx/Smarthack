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
- `DEFAULT_AGENT_DATA_SOURCE`
- `DEFAULT_APP_ENV`
- `DEFAULT_DATA_DIR`
- `DEFAULT_EXAMPLE_SERVICE_URL`
- `DEFAULT_HOST`
- `DEFAULT_HTTP_TIMEOUT`
- `DEFAULT_LOG_LEVEL`
- `DEFAULT_MAINTENANCE_DATA_DIR`
- `DEFAULT_MAINTENANCE_INTERVAL_MINUTES`
- `DEFAULT_MAINTENANCE_MODELS_DIR`
- `DEFAULT_PORT`
- `DEFAULT_TIMEZONE`
- `DEFAULT_WIND_DATA_DIR`
- `DEFAULT_WIND_MODELS_DIR`
- `agent_data_source`
- `app_env`
- `data_dir`
- `example_service_url`
- `frontend_dist_dir`
- `gemini_api_key`
- `host`
- `http_timeout`
- `log_level`
- `maintenance_data_dir`
- `maintenance_demo_scenarios`
- `maintenance_interval_minutes`
- `maintenance_models_dir`
- `port`
- `supabase_key`
- `supabase_service_key`
- `supabase_url`
- `timezone`
- `wind_data_dir`
- `wind_models_dir`
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from smarthack.constants import DEFAULT_MAINTENANCE_INTERVAL_MINUTES

#: Where the dispatch agent reads its data from when `AGENT_DATA_SOURCE` is not set.
DEFAULT_AGENT_DATA_SOURCE = "memory"

#: The environment the application runs in when `APP_ENV` is not set.
DEFAULT_APP_ENV = "development"

#: The logging level when `LOG_LEVEL` is not set.
DEFAULT_LOG_LEVEL = "INFO"

#: The directory holding raw wind observations when `WIND_DATA_DIR` is not set.
DEFAULT_WIND_DATA_DIR = "data/wind"

#: The directory holding trained model artifacts when `WIND_MODELS_DIR` is not set.
DEFAULT_WIND_MODELS_DIR = "models/wind"

#: The directory holding maintenance datasets when `MAINTENANCE_DATA_DIR` is not set.
DEFAULT_MAINTENANCE_DATA_DIR = "data/maintenance"

#: The directory holding maintenance model artifacts when `MAINTENANCE_MODELS_DIR` is not set.
DEFAULT_MAINTENANCE_MODELS_DIR = "models/maintenance"

#: The default IANA timezone when `SMARTHACK_TIMEZONE` is not set.
DEFAULT_TIMEZONE = "UTC"
#: The host to bind the server to when `SMARTHACK_HOST` is not set.
DEFAULT_HOST = "127.0.0.1"

#: The port to bind the server to when `SMARTHACK_PORT` is not set.
DEFAULT_PORT = 8000

#: The default HTTP request timeout in seconds when `SMARTHACK_HTTP_TIMEOUT` is not set.
DEFAULT_HTTP_TIMEOUT = 30.0

#: The default URL for the example upstream service.
DEFAULT_EXAMPLE_SERVICE_URL = "http://localhost:9000"

#: The default data directory relative to repository root.
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

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


def agent_data_source() -> str:
    """
    Return where the dispatch agent reads its crews, turbines and health predictions from.

    :returns source: `"supabase"` to use the database tables; anything else means the
        in-memory seed data. Defaults to `"memory"`.
    """
    return (os.environ.get("AGENT_DATA_SOURCE") or DEFAULT_AGENT_DATA_SOURCE).strip().lower()


def log_level() -> str:
    """
    Return the configured logging level name.

    :returns level: An upper-case level name. Defaults to `"INFO"`.
    """
    return (os.environ.get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()


def wind_data_dir() -> Path:
    """
    Return the path to the directory containing wind observation datasets.

    :returns path: Configured Path to wind data directory.
    """
    raw = os.environ.get("WIND_DATA_DIR") or DEFAULT_WIND_DATA_DIR
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


def wind_models_dir() -> Path:
    """
    Return the path to the directory containing serialized wind model artifacts.

    :returns path: Configured Path to models directory.
    """
    raw = os.environ.get("WIND_MODELS_DIR") or DEFAULT_WIND_MODELS_DIR
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


def maintenance_data_dir() -> Path:
    """
    Return the path to the directory containing maintenance observation datasets.

    :returns path: Configured Path to maintenance data directory.
    """
    raw = os.environ.get("MAINTENANCE_DATA_DIR") or DEFAULT_MAINTENANCE_DATA_DIR
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


def maintenance_models_dir() -> Path:
    """
    Return the path to the directory containing serialized maintenance model artifacts.

    :returns path: Configured Path to maintenance models directory.
    """
    raw = os.environ.get("MAINTENANCE_MODELS_DIR") or DEFAULT_MAINTENANCE_MODELS_DIR
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


def host() -> str:
    """
    Return the host the server listens on.

    :returns host: An IP address or hostname. Defaults to `"127.0.0.1"`.
    """
    return (os.environ.get("SMARTHACK_HOST") or DEFAULT_HOST).strip()


def port() -> int:
    """
    Return the port the server listens on.

    :returns port: An integer port number. Defaults to `8000`.
    """
    raw = os.environ.get("SMARTHACK_PORT")
    if raw is None or not raw.strip():
        return DEFAULT_PORT
    return int(raw.strip())


def frontend_dist_dir() -> Path:
    """
    Return the path to the built frontend distribution directory.

    :returns path: The directory containing `index.html` and static assets.
    """
    raw = os.environ.get("SMARTHACK_FRONTEND_DIST")
    if raw and raw.strip():
        return Path(raw.strip()).resolve()
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


def http_timeout() -> float:
    """
    Return the default timeout in seconds for outbound HTTP requests.

    :returns seconds: Float timeout value in seconds. Defaults to `30.0`.
    """
    raw = os.environ.get("SMARTHACK_HTTP_TIMEOUT")
    if raw is None or not raw.strip():
        return DEFAULT_HTTP_TIMEOUT
    return float(raw.strip())


def data_dir() -> Path:
    """
    Return the base directory for local data files.

    :returns path: Resolved Path object for the data directory.
    """
    raw = os.environ.get("SMARTHACK_DATA_DIR")
    if raw and raw.strip():
        return Path(raw.strip()).resolve()
    return DEFAULT_DATA_DIR


def example_service_url() -> str:
    """
    Return the base URL for the example upstream service.

    :returns url: The base service URL without trailing slash.
    """
    return (
        (os.environ.get("SMARTHACK_EXAMPLE_SERVICE_URL") or DEFAULT_EXAMPLE_SERVICE_URL)
        .strip()
        .rstrip("/")
    )


def supabase_url() -> str:
    """
    Return the base URL of the Supabase project.

    :returns url: The project URL without trailing slash, such as
        `"https://<project-ref>.supabase.co"`.
    :raises RuntimeError: When `SUPABASE_URL` is not set.
    """
    raw = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    if not raw:
        raise RuntimeError("SUPABASE_URL is not set; see .env.example")
    return raw


def supabase_key() -> str:
    """
    Return the Supabase API key used for REST requests.

    :returns key: The `anon` or `service_role` key from the Supabase dashboard.
    :raises RuntimeError: When `SUPABASE_KEY` is not set.
    """
    raw = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not raw:
        raise RuntimeError("SUPABASE_KEY is not set; see .env.example")
    return raw


def gemini_api_key() -> str:
    """
    Return the Google Gemini API key if configured.

    :returns key: API key string or empty string when unset.
    """
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def timezone() -> str:
    """
    Return the application timezone for daily business logic.

    :returns tz: Valid IANA timezone name. Defaults to `"UTC"`.
    :raises ValueError: When `SMARTHACK_TIMEZONE` is not a valid IANA timezone.
    """
    raw = (os.environ.get("SMARTHACK_TIMEZONE") or DEFAULT_TIMEZONE).strip()
    ZoneInfo(raw)
    return raw


def supabase_service_key() -> str:
    """
    Return the secret service-role Supabase key for administrative background jobs.

    :returns key: Service role key string with RLS bypass privileges.
    :raises RuntimeError: When neither `SUPABASE_SERVICE_KEY` nor `SUPABASE_KEY` is set.
    """
    raw = (
        (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY") or "")
        .strip()
        .strip('"')
        .strip("'")
    )
    for prefix in ("service role", "service_role", "anon public", "anon", "publishable"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix) :].strip()
    if not raw:
        raise RuntimeError("SUPABASE_SERVICE_KEY or SUPABASE_KEY is not set; see .env.example")
    return raw


def maintenance_interval_minutes() -> int:
    """
    Return the scheduled interval in minutes between background maintenance runs.

    :returns minutes: Integer minutes between cycles. Defaults to `60`.
    """
    raw = os.environ.get("MAINTENANCE_INTERVAL_MINUTES")
    if raw is None or not raw.strip():
        return DEFAULT_MAINTENANCE_INTERVAL_MINUTES
    return int(raw.strip())


def maintenance_demo_scenarios() -> dict[int, str]:
    """
    Return mapping from turbine ID to simulated demo failure scenario.

    :returns scenarios: Dictionary mapping asset ID integer to scenario name string.
    """
    raw = (os.environ.get("MAINTENANCE_DEMO_SCENARIOS") or "").strip()
    if not raw:
        return {}
    scenarios: dict[int, str] = {}
    for item in raw.split(","):
        parts = item.strip().split(":")
        if len(parts) == 2 and parts[0].strip().isdigit():
            scenarios[int(parts[0].strip())] = parts[1].strip()
    return scenarios


__all__ = [
    "DEFAULT_AGENT_DATA_SOURCE",
    "DEFAULT_APP_ENV",
    "DEFAULT_DATA_DIR",
    "DEFAULT_EXAMPLE_SERVICE_URL",
    "DEFAULT_HOST",
    "DEFAULT_HTTP_TIMEOUT",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_MAINTENANCE_DATA_DIR",
    "DEFAULT_MAINTENANCE_INTERVAL_MINUTES",
    "DEFAULT_MAINTENANCE_MODELS_DIR",
    "DEFAULT_PORT",
    "DEFAULT_TIMEZONE",
    "DEFAULT_WIND_DATA_DIR",
    "DEFAULT_WIND_MODELS_DIR",
    "agent_data_source",
    "app_env",
    "data_dir",
    "example_service_url",
    "frontend_dist_dir",
    "gemini_api_key",
    "host",
    "http_timeout",
    "log_level",
    "maintenance_data_dir",
    "maintenance_demo_scenarios",
    "maintenance_interval_minutes",
    "maintenance_models_dir",
    "port",
    "supabase_key",
    "supabase_service_key",
    "supabase_url",
    "timezone",
    "wind_data_dir",
    "wind_models_dir",
]
