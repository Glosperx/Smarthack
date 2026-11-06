"""`skip_if_optional`: a missing extra shrinks the registry, anything else still fails."""

import logging

import pytest

from smarthack.utils.optional_imports import skip_if_optional

OPTIONAL = ("boto3", "botocore")


def test_a_declared_optional_module_is_skipped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The caller's registry goes without the entry, and the log says what is missing."""
    exc = ModuleNotFoundError("No module named 'boto3'", name="boto3")

    with caplog.at_level(logging.WARNING):
        skip_if_optional(exc, "S3Store", OPTIONAL)

    assert "S3Store" in caplog.text
    assert "boto3" in caplog.text


def test_a_submodule_counts_as_its_top_level_package() -> None:
    """`botocore.exceptions` missing is `botocore` missing."""
    exc = ModuleNotFoundError("No module named 'botocore.exceptions'", name="botocore.exceptions")

    skip_if_optional(exc, "S3Store", OPTIONAL)


def test_warn_false_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    """A package that re-exports the class reports the missing extra only once."""
    exc = ModuleNotFoundError("No module named 'boto3'", name="boto3")

    with caplog.at_level(logging.WARNING):
        skip_if_optional(exc, "S3Store", OPTIONAL, warn=False)

    assert caplog.text == ""


def test_an_undeclared_module_is_re_raised_unchanged() -> None:
    """A typo in our own code must not be mistaken for an uninstalled extra."""
    exc = ModuleNotFoundError("No module named 'smarthack.typo'", name="smarthack.typo")

    with pytest.raises(ModuleNotFoundError) as raised:
        skip_if_optional(exc, "S3Store", OPTIONAL)

    assert raised.value is exc


def test_an_error_with_no_module_name_is_re_raised() -> None:
    """Without a name there is nothing to compare, and the safe answer is to fail."""
    exc = ImportError("cannot import name 'X' from 'smarthack.y'")

    with pytest.raises(ImportError):
        skip_if_optional(exc, "X", OPTIONAL)


def test_a_lookalike_prefix_is_not_a_declared_module() -> None:
    """`boto3_extra` is not `boto3`: names are compared whole, not by prefix."""
    exc = ModuleNotFoundError("No module named 'boto3_extra'", name="boto3_extra")

    with pytest.raises(ModuleNotFoundError):
        skip_if_optional(exc, "S3Store", OPTIONAL)
