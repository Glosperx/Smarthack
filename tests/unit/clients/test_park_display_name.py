"""
# Unit tests for the park name lookup

The alerts name a park the way a person knows it. The lookup reads the `park` table once per park
and never fails an alert: any problem gives back the id.
"""

from typing import Any

import httpx
import pytest

from smarthack.clients import supabase


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no names cached and the Supabase source on."""
    monkeypatch.setattr(supabase, "_PARK_NAMES", {})
    monkeypatch.setenv("AGENT_DATA_SOURCE", "supabase")


def test_a_known_park_comes_back_by_name_and_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second ask for the same park does not reach the database."""
    asked: list[dict[str, str]] = []

    def select_rows(relation: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        asked.append(params or {})
        return [{"id": 24, "name": "Valea Nucarilor (Agighiol)"}]

    monkeypatch.setattr(supabase, "select_rows", select_rows)

    assert supabase.park_display_name(24) == "Valea Nucarilor (Agighiol)"
    assert supabase.park_display_name("24") == "Valea Nucarilor (Agighiol)"
    assert asked == [{"select": "id,name", "id": "eq.24"}]


def test_the_memory_source_and_non_numeric_ids_give_the_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """No database read happens for an id that has no row to find."""

    def select_rows(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("the database must not be read")

    monkeypatch.setattr(supabase, "select_rows", select_rows)

    assert supabase.park_display_name("wind_farm_a") == "wind_farm_a"
    monkeypatch.setenv("AGENT_DATA_SOURCE", "memory")
    assert supabase.park_display_name(24) == "24"


@pytest.mark.parametrize("outcome", [httpx.ConnectError("down"), RuntimeError("no key"), [], [{}]])
def test_an_unreadable_or_missing_name_gives_the_id(
    monkeypatch: pytest.MonkeyPatch, outcome: Any
) -> None:
    """A database error, a park with no row or a row with no name never holds an alert back."""

    def select_rows(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if isinstance(outcome, Exception):
            raise outcome
        return list(outcome)

    monkeypatch.setattr(supabase, "select_rows", select_rows)

    assert supabase.park_display_name(24) == "24"
