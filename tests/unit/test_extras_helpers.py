"""
The helpers in `tests/conftest.py` that let a test skip on a core install.

They are the only thing standing between a missing optional extra and a red CI, so
they are tested while `EXTRA_MODULES` is still empty, with a made-up extra.
"""

import pytest

from tests import conftest
from tests.conftest import (
    _skip_reason,
    extra_is_installed,
    missing_extra,
    requires_extra,
)

PRESENT = "json"
ABSENT = "no_such_module_for_smarthack_tests"


@pytest.fixture(autouse=True)
def made_up_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Declare two extras: one whose module exists, one whose module does not.

    :param monkeypatch: pytest's patcher, which restores `EXTRA_MODULES` after the test.
    """
    monkeypatch.setitem(conftest.EXTRA_MODULES, "present", (PRESENT,))
    monkeypatch.setitem(conftest.EXTRA_MODULES, "absent", (ABSENT,))
    monkeypatch.setitem(conftest.EXTRA_MODULES, "also_absent", (ABSENT, "another_missing"))


def test_an_extra_is_installed_only_when_every_module_is_found() -> None:
    """`find_spec` answers without importing anything."""
    assert extra_is_installed("present")
    assert not extra_is_installed("absent")


def test_a_skip_reason_names_the_extra_and_the_command_that_installs_it() -> None:
    """One extra, two, and three read as English, and the pip line lists all of them."""
    assert _skip_reason(("aws",)) == "needs the 'aws' extra: pip install -e \".[aws]\""
    assert _skip_reason(("aws", "excel")) == (
        "needs the 'aws' and 'excel' extras: pip install -e \".[aws,excel]\""
    )
    assert _skip_reason(("a", "b", "c")).startswith("needs the 'a', 'b' and 'c' extras")


def test_requires_extra_skips_only_when_something_is_missing() -> None:
    """The marker is a `skipif` that fires for an absent extra and not for a present one."""
    assert requires_extra("present").args == (False,)
    assert requires_extra("absent").args == (True,)
    assert requires_extra("present", "absent").args == (True,)


def test_missing_extra_names_every_absent_extra_that_brings_the_module() -> None:
    """Two extras bringing the same module are both named, joined by 'or'."""
    exc = ModuleNotFoundError("No module named", name=ABSENT)

    assert missing_extra(exc) == "'absent' or 'also_absent'"


def test_a_submodule_of_a_missing_module_counts_as_the_module() -> None:
    """`pkg.sub` missing is `pkg` missing."""
    exc = ModuleNotFoundError("No module named", name=f"{ABSENT}.sub")

    assert missing_extra(exc) is not None


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("smarthack.typo", id="our-own-module"),
        pytest.param(PRESENT, id="module-of-an-installed-extra"),
        pytest.param(None, id="no-module-name"),
    ],
)
def test_anything_else_is_a_bug_and_not_a_missing_extra(name: str | None) -> None:
    """Only a module of a declared, absent extra may be skipped around."""
    assert missing_extra(ModuleNotFoundError("No module named", name=name)) is None
