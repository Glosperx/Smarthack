"""
The files around the package that promise something about it.

`.env.example`, `pyproject.toml`, `.pre-commit-config.yaml` and the CI workflow are
read by people and by CI, never by the package's own tests, so a promise one of
them makes can quietly stop being kept:

- `.env.example` sets a variable nothing reads, or `config.py` reads one the
  example never mentions;
- an accessor in `config.py` that no code calls is a setting that does nothing;
- black, isort or flake8 is pinned to one version in `pyproject.toml` and another
  in pre-commit, so a commit passes locally and fails in CI;
- an extra is added to `pyproject.toml` and the tests never learn which modules it
  brings, so they fail on a core install instead of skipping.
"""

from pathlib import Path
import re
import tomllib

import smarthack
import smarthack.config as config
from tests.conftest import EXTRA_MODULES

#: The repository's root: the package's parent directory.
REPO_ROOT = Path(smarthack.__file__).parent.parent

#: Variables `.env.example` sets that a library reads, never the application.
#: A variable of boto3, say, goes here with the library's name beside it.
READ_BY_A_LIBRARY: set[str] = set()

#: Extras that are tools, not features, and bring nothing the tests import.
TOOL_EXTRAS = {"dev", "docs", "all"}

#: The tools whose pin in `pyproject.toml` must equal the `rev:` of their pre-commit hook.
PINNED_IN_BOTH = ("black", "isort", "flake8")


def test_every_variable_the_example_sets_is_read_by_something() -> None:
    """Each uncommented `NAME=value` is read by `config.py`, or named as a library's."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    names = re.findall(r"^([A-Z][A-Z0-9_]*)=", example, flags=re.MULTILINE)
    source = Path(config.__file__).read_text(encoding="utf-8")

    unread = [name for name in names if f'"{name}"' not in source and name not in READ_BY_A_LIBRARY]

    assert names, "no variable found: the pattern no longer matches the file"
    assert unread == []


def test_every_variable_config_reads_is_in_the_example() -> None:
    """The other direction: `.env.example` is the setup documentation, so it must be complete."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    source = Path(config.__file__).read_text(encoding="utf-8")
    read = re.findall(r'os\.environ\.get\("([A-Z][A-Z0-9_]*)"', source)

    undocumented = [
        name for name in read if not re.search(rf"^#?\s*{name}=", example, re.MULTILINE)
    ]

    assert read, "no variable found: the pattern no longer matches config.py"
    assert undocumented == []


def test_every_accessor_of_the_configuration_is_called_somewhere() -> None:
    """
    An accessor nothing calls is a setting that does nothing: it reads a variable
    and hands it to no one. Each function `config` exports is called somewhere in
    the package.
    """
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in Path(smarthack.__file__).parent.rglob("*.py")
    )
    accessors = [name for name in config.__all__ if callable(getattr(config, name))]

    uncalled = [name for name in accessors if not re.search(rf"(?<!def ){name}\(", sources)]

    assert accessors, "no accessor found"
    assert uncalled == []


def test_black_isort_and_flake8_are_pinned_to_the_same_version_in_pre_commit() -> None:
    """
    A formatter pinned twice, to two versions, formats twice: pre-commit passes, CI fails.

    `pyproject.toml` pins what CI installs, `.pre-commit-config.yaml` what the git
    hook runs. They must name the same version.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]
    pinned = {
        match.group(1): match.group(2)
        for requirement in dev
        if (match := re.fullmatch(r"([A-Za-z0-9_.-]+)==(\S+)", requirement))
    }
    hooks = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    revs = {
        match.group(1): match.group(2).removeprefix("v")
        for match in re.finditer(r"repo:\s*\S+/([\w.-]+)\s*\n\s*rev:\s*(\S+)", hooks)
    }

    for tool in PINNED_IN_BOTH:
        assert tool in pinned, f"{tool} is not pinned with == in the dev extra"
        assert tool in revs, f"{tool} has no hook in .pre-commit-config.yaml"
        assert (
            pinned[tool] == revs[tool]
        ), f"{tool}: pyproject.toml pins {pinned[tool]}, pre-commit runs {revs[tool]}"


def test_every_feature_extra_has_its_modules_listed_for_the_tests() -> None:
    """
    An extra the tests know nothing about cannot be skipped around.

    `EXTRA_MODULES` in `tests/conftest.py` says which import names each extra brings,
    which is how a test skips on a core install instead of failing. Vacuously true
    until the first feature extra is added to `pyproject.toml`.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = set(pyproject["project"]["optional-dependencies"]) - TOOL_EXTRAS

    assert extras - set(EXTRA_MODULES) == set()


def test_the_ci_workflow_runs_the_same_lint_and_tests_as_make() -> None:
    """CI calls the Makefile targets, so what passes locally is what CI checks."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "make lint" in workflow
    assert "make cov" in workflow
    assert "make docs" in workflow
