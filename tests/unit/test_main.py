"""The entry point: it logs what it started with and exits cleanly."""

import logging

import pytest

import smarthack
from smarthack.__main__ import main


def test_main_returns_zero_and_logs_name_version_and_environment(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean start is exit code 0 and one line saying what started."""
    monkeypatch.setenv("APP_ENV", "staging")

    with caplog.at_level(logging.INFO):
        code = main()

    assert code == 0
    assert f"smarthack {smarthack.__version__} started in the staging environment" in caplog.text
