"""
# Shared test fixtures

Fixtures and helpers every test gets for free.

The autouse fixture isolates each test from the developer's own environment: a
`LOG_LEVEL=DEBUG` in a local `.env` must not change what a test sees, and a test
must not leave a variable behind for the next one.

The three helpers for optional extras live here for the same reason. The suite
runs on two installs — everything, and the core alone — and a test that needs an
extra must say so and **skip** on the core install, naming the extra, rather than
fail there. Which import names each extra brings is written down once, in
`EXTRA_MODULES`. They are plain functions, imported with
`from tests.conftest import ...`, because a decorator or a call at the top of a
test file cannot be a fixture.

Assertion helpers for a domain (a metric set, a response shape) go here as well,
so that when the shape changes there is one place to edit, not six test files.

Run `pytest -m "not integration"` while editing: the `integration` marker holds
what starts a process, chains steps or talks to a service.
"""

import importlib.util
from typing import Iterator

import pytest

#: The import names each optional extra of `pyproject.toml` brings, as far as the
#: tests are concerned. A new extra gets a line here, and
#: `test_repository_files.py` fails until it has one. Empty until the first extra.
EXTRA_MODULES: dict[str, tuple[str, ...]] = {
    "calls": ("jinja2", "requests", "twilio"),
    "lake": ("watchdog",),
    "resource": ("imagecodecs", "numpy", "PIL", "tifffile"),
    "transport": ("numpy", "osmium"),
    "wind": (
        "catboost",
        "joblib",
        "lightgbm",
        "numpy",
        "pandas",
        "requests",
        "sklearn",
        "xgboost",
    ),
    "monitoring": ("langchain", "langfuse"),
}

#: Variables of `.env.example` a developer may have set locally, removed for every test.
_ENVIRONMENT_VARIABLES = (
    "APP_ENV",
    "LOG_LEVEL",
    "WIND_DATA_DIR",
    "WIND_MODELS_DIR",
    "LAKE_DIR",
    "MAINTENANCE_MODELS_DIR",
    "MAINTENANCE_DATA_DIR",
    "RESOURCE_CACHE_DIR",
    "RESOURCE_ATLAS_DIR",
    "TRANSPORT_CACHE_DIR",
    "TRANSPORT_NETWORK_DIR",
    "SMARTHACK_HOST",
    "SMARTHACK_PORT",
    "SMARTHACK_FRONTEND_DIST",
    "SMARTHACK_HTTP_TIMEOUT",
    "SMARTHACK_DATA_DIR",
    "SMARTHACK_EXAMPLE_SERVICE_URL",
    "SMARTHACK_TIMEZONE",
    "AGENT_DATA_SOURCE",
    "GEMINI_API_KEY",
    "DECISION_MODEL_ENABLED",
    "DECISION_MODEL_URL",
    "DECISION_MODEL_MODE",
    "LANGFUSE_ENABLED",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "MAINTENANCE_INTERVAL_MINUTES",
    "MAINTENANCE_DEMO_SCENARIOS",
    "WIND_FORECAST_INTERVAL_MINUTES",
    "OPEN_METEO_URL",
    "VOICE_CALLS_ENABLED",
)


def extra_is_installed(extra: str) -> bool:
    """
    Report whether every module an extra brings can be imported.

    `find_spec` looks the module up without importing it, so asking costs nothing
    and runs none of our own code.

    :param extra: A key of `EXTRA_MODULES`.

    :returns installed: True when all of the extra's modules are present.
    """
    return all(importlib.util.find_spec(name) is not None for name in EXTRA_MODULES[extra])


def _skip_reason(extras: tuple[str, ...]) -> str:
    """
    Word the reason a test is skipped, with the command that would run it.

    :param extras: The extras the test needs.

    :returns reason: Such as `needs the 'aws' extra: pip install -e ".[aws]"`.
    """
    quoted = [f"'{extra}'" for extra in extras]
    named = quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} and {quoted[-1]}"
    noun = "extra" if len(extras) == 1 else "extras"
    return f'needs the {named} {noun}: pip install -e ".[{",".join(extras)}]"'


def requires_extra(*extras: str) -> pytest.MarkDecorator:
    """
    Mark a test that needs optional extras; it skips when one is missing.

    :param extras: Keys of `EXTRA_MODULES`.

    :returns marker: A `skipif` marker naming the extras in its reason.
    """
    missing = not all(extra_is_installed(extra) for extra in extras)
    return pytest.mark.skipif(missing, reason=_skip_reason(extras))


def skip_module_without_extra(*extras: str) -> None:
    """
    Skip a whole test file when an extra it needs is missing.

    Called at the top of the file, **before** it imports the module under test:
    that import is exactly what fails without the extra, and a failure at import
    time is a collection error, which no marker can turn into a skip.

    :param extras: Keys of `EXTRA_MODULES`.
    """
    # Makes pytest report the skip at the calling test file's line, not here.
    __tracebackhide__ = True
    if not all(extra_is_installed(extra) for extra in extras):
        pytest.skip(_skip_reason(extras), allow_module_level=True)


def missing_extra(exc: ModuleNotFoundError) -> str | None:
    """
    Tell a missing extra apart from a real import bug.

    The registries' filter, made stricter: the missing module must belong to a
    declared extra, **and** that extra must really be absent. Anything else — our
    own module, a typo, an error with no module name — is a bug and must still
    fail.

    Several extras can bring the same module, so every extra that would is named
    rather than the first in the table.

    :param exc: The error raised while importing a module of the package.

    :returns extras: The missing extras that bring the module, quoted and joined
        by "or", such as `'aws' or 'storage'`; or None when the error is
        something else.
    """
    top = (exc.name or "").split(".")[0]
    extras = [
        f"'{extra}'"
        for extra, modules in EXTRA_MODULES.items()
        if top in modules and not extra_is_installed(extra)
    ]
    return " or ".join(extras) or None


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Isolate every test from the developer's environment.

    Removes the variables `.env.example` documents, so a value from a local `.env`
    (loaded when `smarthack.config` is imported) never reaches a test. `monkeypatch`
    restores the previous environment when the test ends.

    :param monkeypatch: pytest's environment patcher.

    :returns: Yields control to the test.
    """
    for name in _ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    yield
