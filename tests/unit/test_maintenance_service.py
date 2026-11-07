"""Unit tests for the predictive maintenance orchestration service."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from smarthack.constants import NO_SUBSYSTEM
from smarthack.schemas.maintenance import PredictionRow
from smarthack.services.maintenance_service import _to_row, run_prediction_cycle, scenario_for


def test_scenario_for_defaults_to_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unmapped turbine asset ID defaults to the normal scenario profile."""
    monkeypatch.delenv("MAINTENANCE_DEMO_SCENARIOS", raising=False)
    assert scenario_for(999) == "normal"


def test_scenario_for_uses_configured_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mapped turbine asset ID returns its configured scenario profile."""
    monkeypatch.setenv("MAINTENANCE_DEMO_SCENARIOS", "42:gearbox_overheating")
    assert scenario_for(42) == "gearbox_overheating"
    assert scenario_for(43) == "normal"


def test_to_row_valid_payload() -> None:
    """Raw model output transforms accurately into a validated PredictionRow."""
    raw = {
        "fault_probability": 0.35,
        "health_status": "WATCH",
        "suspected_subsystem": "gearbox",
        "health_score": 78.5,
        "estimated_days_to_failure": 14.0,
        "anomalous_sensors": ["gearbox_vibration_axial"],
        "summary_text": "Elevated gearbox vibration detected.",
        "daily_forecast": [
            {"day": 1, "fault_probability": 0.35, "cumulative_fault_probability": 0.42}
        ],
    }
    today = date(2026, 11, 7)
    row = _to_row(10, today, raw)

    assert isinstance(row, PredictionRow)
    assert row.turbine_id == 10
    assert row.predicted_date == today
    assert row.daily_fault_probability == 0.35
    assert row.cumulative_fault_probability == 0.42
    assert row.status == "WATCH"
    assert row.suspected_subsystem == "gearbox"
    assert row.health_score == 78.5
    assert row.estimated_days_to_failure == 14.0
    assert row.anomalous_sensors == ["gearbox_vibration_axial"]
    assert row.summary_text == "Elevated gearbox vibration detected."


def test_to_row_empty_subsystem_normalizes_to_none() -> None:
    """Empty or missing suspected subsystem normalizes to the NO_SUBSYSTEM constant."""
    raw = {
        "fault_probability": 0.05,
        "health_status": "NORMAL",
        "suspected_subsystem": "   ",
    }
    today = date(2026, 11, 7)
    row = _to_row(1, today, raw)

    assert row.suspected_subsystem == NO_SUBSYSTEM
    assert row.cumulative_fault_probability == 0.05


def test_run_prediction_cycle_dry_run() -> None:
    """Dry run computes predictions across turbines without calling upsert."""
    today = date(2026, 11, 7)
    fake_http = AsyncMock(spec=httpx.AsyncClient)

    with patch(
        "smarthack.clients.supabase.fetch_maintenance_inputs",
        new_callable=AsyncMock,
        return_value={},
    ):
        with patch("smarthack.clients.supabase.upsert_predictions") as mock_upsert:
            summary = asyncio.run(
                run_prediction_cycle(
                    fake_http,
                    day=today,
                    turbine_ids=[1, 2],
                    dry_run=True,
                )
            )

            assert summary.total == 2
            assert summary.written == 0
            assert summary.failed == 0
            assert mock_upsert.call_count == 0
            assert "NORMAL" in summary.by_status or len(summary.by_status) > 0


def test_run_prediction_cycle_skips_empty_telemetry() -> None:
    """Turbine with empty telemetry records is recorded as no_data and skipped."""
    today = date(2026, 11, 7)
    fake_http = AsyncMock(spec=httpx.AsyncClient)

    async def _mock_telemetry(tid: int) -> list[dict[str, object]]:
        return []

    with patch(
        "smarthack.clients.supabase.fetch_maintenance_inputs",
        new_callable=AsyncMock,
        return_value={},
    ):
        with patch("smarthack.clients.supabase.upsert_predictions") as mock_upsert:
            summary = asyncio.run(
                run_prediction_cycle(
                    fake_http,
                    day=today,
                    get_telemetry=_mock_telemetry,
                    turbine_ids=[5],
                    dry_run=False,
                )
            )

            assert summary.total == 1
            assert summary.written == 0
            assert summary.no_data == 1
            assert mock_upsert.call_count == 0


def test_run_prediction_cycle_handles_turbine_exception() -> None:
    """Assessment failure on one turbine increments failed count and does not crash cycle."""
    today = date(2026, 11, 7)
    fake_http = AsyncMock(spec=httpx.AsyncClient)

    with patch(
        "smarthack.clients.supabase.fetch_maintenance_inputs",
        new_callable=AsyncMock,
        return_value={},
    ):
        with patch(
            "smarthack.services.maintenance_service.assess_turbine_health",
            side_effect=[RuntimeError("Engine boom"), {"fault_probability": 0.1}],
        ):
            with patch(
                "smarthack.clients.supabase.upsert_predictions", new_callable=AsyncMock
            ) as mock_upsert:
                summary = asyncio.run(
                    run_prediction_cycle(
                        fake_http,
                        day=today,
                        turbine_ids=[101, 102],
                        dry_run=False,
                    )
                )

                assert summary.total == 2
                assert summary.failed == 1
                assert summary.written == 1
                assert mock_upsert.call_count == 1


def test_run_prediction_cycle_uses_database_feature_inputs() -> None:
    """When pre-computed database inputs exist, they are passed directly to the model."""
    today = date(2026, 11, 7)
    fake_http = AsyncMock(spec=httpx.AsyncClient)
    mock_inputs = {
        10: {
            "turbine_id": 10,
            "thermal_lift_bearing_de": 52.0,
            "bearing_temp_ratio": 1.45,
            "sensor_0_avg": 22.0,
        }
    }

    with patch(
        "smarthack.clients.supabase.fetch_maintenance_inputs",
        new_callable=AsyncMock,
        return_value=mock_inputs,
    ):
        with patch(
            "smarthack.clients.supabase.upsert_predictions", new_callable=AsyncMock
        ) as mock_upsert:
            summary = asyncio.run(
                run_prediction_cycle(
                    fake_http,
                    day=today,
                    turbine_ids=[10],
                    dry_run=False,
                )
            )

            assert summary.total == 1
            assert summary.written == 1
            assert mock_upsert.call_count == 1
            rows = mock_upsert.call_args[0][1]
            assert rows[0]["turbine_id"] == 10
            assert rows[0]["status"] in ("WATCH", "WARNING", "CRITICAL")
            assert rows[0]["suspected_subsystem"] == "Generator Bearing"
