"""
The gate for the one documentation rule nothing else checks.

`docstr-coverage` counts whether a docstring exists, never what is in it. But
every module is required to end its docstring with the list of what it exports,
and that list is the module's public contract — the thing a reviewer would catch
if a new function were added and the list left stale. With no reviewer, this test
is the reviewer.

As a side effect it imports every module in the package, which catches syntax
errors and circular imports in modules nothing has registered yet.

A module that needs an optional extra is skipped when that extra is missing. Only
that: any other import error still fails.
"""

import importlib
import pkgutil
import re
from types import ModuleType

import pytest

import smarthack
from tests.conftest import missing_extra

MARKER = "The following can be imported from this module:"


def all_modules() -> list[str]:
    """
    List every importable module in the package.

    :returns names: Dotted module names, the package itself included.
    """
    names = [smarthack.__name__]
    for info in pkgutil.walk_packages(smarthack.__path__, f"{smarthack.__name__}."):
        names.append(info.name)
    return sorted(names)


def documented_exports(module: ModuleType) -> set[str]:
    """
    Parse the "can be imported" list out of a module docstring.

    Bullet lines carry the names in backticks. A module that exports nothing says
    so in prose with no backticks, which parses to the empty set — exactly what
    its empty `__all__` produces.

    :param module: The imported module.

    :returns names: The names the docstring claims are importable.
    """
    doc = module.__doc__ or ""
    _, _, tail = doc.partition(MARKER)
    return set(re.findall(r"^\s*-\s*`([^`]+)`", tail, flags=re.MULTILINE))


def import_or_skip(module_name: str) -> ModuleType:
    """
    Import a module of the package, skipping the test if an extra it needs is missing.

    :param module_name: Dotted name of the module.

    :returns module: The imported module.

    :raises ModuleNotFoundError: When the missing module is not part of a
        declared extra — that is a bug, not an uninstalled extra.
    """
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        extra = missing_extra(exc)
        if extra is None:
            raise
        pytest.skip(f"{module_name} needs the {extra} extra")


MODULE_NAMES = all_modules()


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_module_has_a_docstring_with_the_export_list(module_name: str) -> None:
    """
    Every module states what can be imported from it.

    A package that exports nothing says so in prose and has no list to check: the
    marker is required of every module that has an `__all__` to compare it with.
    """
    module = import_or_skip(module_name)
    assert module.__doc__, f"{module_name} has no module docstring"
    if getattr(module, "__all__", []):
        assert MARKER in module.__doc__, f"{module_name} is missing the {MARKER!r} list"


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_export_list_matches_dunder_all(module_name: str) -> None:
    """
    The documented list and `__all__` say the same thing.

    This is what fails when someone adds a function and updates only one of the two.
    """
    module = import_or_skip(module_name)
    declared = set(getattr(module, "__all__", []))
    documented = documented_exports(module)
    assert (
        documented == declared
    ), f"{module_name}: docstring lists {sorted(documented)} but __all__ is {sorted(declared)}"


def test_the_documented_list_is_parsed_from_the_marker_onwards() -> None:
    """Bullets above the marker describe the module; only those below it are exports."""
    module = ModuleType("fake")
    module.__doc__ = f"""
    - `not_an_export`: a bullet in the prose

    {MARKER}
    - `first`
    - `second`
    """

    assert documented_exports(module) == {"first", "second"}


def test_the_package_actually_has_modules() -> None:
    """Guard against the walk silently finding nothing and the suite passing empty."""
    assert len(MODULE_NAMES) >= 6
