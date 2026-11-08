"""
# Agent tool implementations and function specifications

Callable tools and schemas exposed to the LangGraph autonomous dispatch agent.

The following can be imported from this module:
- `dispatch_voice_alert`
- `dispatch_warning_email`
- `get_available_crews_tool`
- `get_daily_wind_forecast`
- `get_turbine_location`
- `get_turbines_needing_attention`
- `predict_wind_power_mwh`
"""

import logging
from typing import Any

import httpx

from smarthack import config
from smarthack.clients.crew_client import get_default_crew_client
from smarthack.clients.email_client import get_default_email_client
from smarthack.clients.voice_client import get_default_voice_client
from smarthack.constants import WIND_FORECAST_DAYS
from smarthack.schemas.dispatch import CrewStatus
from smarthack.services.agent import db_tools
from smarthack.services.fleet_service import get_default_fleet_service
from smarthack.utils.dates import today_in_tz
from smarthack.wind.agent_tool import predict_wind_power

logger = logging.getLogger(__name__)


def _use_database() -> bool:
    """
    Tell whether the agent reads from Supabase instead of the in-memory seed data.

    :returns flag: True when `AGENT_DATA_SOURCE=supabase`.
    """
    return config.agent_data_source() == "supabase"


def get_turbines_needing_attention(
    park_id: str | None = None,
    scenarios: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve all wind turbines currently predicted to have impending faults.

    :param park_id: Optional wind park identifier to filter candidates.
    :param scenarios: Optional simulation scenario mapping for testing.

    :returns candidates: List of serialized triage dictionaries needing repair.
    """
    if _use_database():
        needing = db_tools.db_get_turbines_needing_attention(park_id=park_id)
        logger.info(
            "Found %d turbines needing repair (db) for park=%s", len(needing), park_id or "ALL"
        )
        return needing

    fleet_svc = get_default_fleet_service()
    if park_id:
        triage_list = fleet_svc.scan_park(park_id, scenarios=scenarios)
    else:
        park_map = fleet_svc.scan_all_parks(scenarios=scenarios)
        triage_list = [item for sublist in park_map.values() for item in sublist]

    needing = [t.model_dump() for t in triage_list if t.needs_repair]
    logger.info("Found %d turbines needing repair for park=%s", len(needing), park_id or "ALL")
    return needing


def get_available_crews_tool(park_id: str) -> list[dict[str, Any]]:
    """
    Retrieve all available maintenance crews strictly dedicated to a specific wind park.

    :param park_id: The wind park identifier.

    :returns crews: List of available crew metadata dictionaries.
    """
    if _use_database():
        return db_tools.db_get_available_crews(park_id)
    crew_client = get_default_crew_client()
    crews = crew_client.get_crews_by_park(park_id=park_id, status=CrewStatus.AVAILABLE)
    return [c.model_dump() for c in crews]


def get_daily_wind_forecast(park_id: str, days: int = WIND_FORECAST_DAYS) -> list[float | None]:
    """
    Read the park's forecast wind speed per day, used to pick the calmest repair day.

    Without a database, or when it cannot be read, returns an empty list: the scheduler then
    plans every repair on the earliest free day instead of failing the whole sweep.

    :param park_id: The wind park identifier.
    :param days: How many days from today to return.

    :returns wind: Mean wind speed in m/s per day from today, None where unknown; may be empty.
    """
    if not _use_database():
        return []
    try:
        return db_tools.db_get_daily_wind(park_id, days, today_in_tz(config.timezone()))
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.warning(
            "Wind forecast unavailable for park %s; planning without it: %s", park_id, exc
        )
        return []


def get_turbine_location(turbine_id: int) -> dict[str, float]:
    """
    Look up the coordinates and rated capacity used to forecast a turbine's output.

    :param turbine_id: Asset identifier.

    :returns location: Dict with `latitude`, `longitude`, `capacity_kw`; site defaults if unknown.
    """
    if _use_database():
        found = db_tools.db_get_turbine_location(turbine_id)
        if found:
            return {k: float(v) for k, v in found.items()}
    else:
        info = get_default_fleet_service().get_turbine_info(turbine_id)
        if info:
            return {
                "latitude": info.latitude,
                "longitude": info.longitude,
                "capacity_kw": info.capacity_kw,
            }
    return {"latitude": 35.2, "longitude": -101.8, "capacity_kw": 2050.0}


def predict_wind_power_mwh(
    latitude: float,
    longitude: float,
    forecast_days: int = 7,
    capacity_kw: float = 2050.0,
) -> float:
    """
    Calculate the projected electricity generation (MWh) over the forecast horizon.

    Invoked exclusively when a crew resource conflict exists to prioritize higher-output assets.

    :param latitude: Geographic latitude coordinate.
    :param longitude: Geographic longitude coordinate.
    :param forecast_days: Number of forecast days ahead (default 7).
    :param capacity_kw: Turbine rated capacity in kW (default 2050.0).

    :returns total_mwh: Cumulative projected electricity production in megawatt-hours.
    """
    result = predict_wind_power(
        latitude=latitude,
        longitude=longitude,
        forecast_days=forecast_days,
        capacity_kw=capacity_kw,
    )
    # Total kWh = mean hourly kW * total hours in forecast
    mean_kw = float(result.get("mean_predicted_kw", 0.0))
    total_hours = len(result.get("hourly_forecast", []))
    if total_hours == 0:
        total_hours = forecast_days * 24

    total_mwh = (mean_kw * total_hours) / 1000.0
    logger.info(
        "Power forecast for (%.2f, %.2f) over %d days: %.2f MWh",
        latitude,
        longitude,
        forecast_days,
        total_mwh,
    )
    return round(total_mwh, 2)


def dispatch_voice_alert(
    phone_number: str,
    crew_name: str,
    turbine_id: int,
    park_id: str,
    message: str,
    lead_time_hours: float | None = None,
) -> dict[str, Any]:
    """
    Dispatch an urgent text-to-speech voice call to the park's maintenance crew.

    :param phone_number: Maintenance lead phone number.
    :param crew_name: Name of the recipient crew.
    :param turbine_id: Asset identifier.
    :param park_id: Wind park identifier.
    :param message: Emergency spoken transcript.
    :param lead_time_hours: Estimated hours to catastrophic failure.

    :returns record: Confirmation record of the voice call.
    """
    voice_client = get_default_voice_client()
    return voice_client.dispatch_emergency_call(
        phone_number=phone_number,
        crew_name=crew_name,
        turbine_id=turbine_id,
        park_id=park_id,
        message=message,
        lead_time_hours=lead_time_hours,
    )


def dispatch_warning_email(
    recipient_email: str,
    crew_name: str,
    turbine_id: int,
    park_id: str,
    subject: str,
    body: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Dispatch a maintenance work order ticket email to the park's crew.

    :param recipient_email: Destination email address.
    :param crew_name: Name of the assigned crew.
    :param turbine_id: Asset identifier.
    :param park_id: Wind park identifier.
    :param subject: Email subject line.
    :param body: Detailed diagnostic body text.
    :param diagnostics: Optional sensor telemetry and risk payload.

    :returns record: Confirmation record of the email dispatch.
    """
    email_client = get_default_email_client()
    return email_client.dispatch_work_ticket(
        recipient_email=recipient_email,
        crew_name=crew_name,
        turbine_id=turbine_id,
        park_id=park_id,
        subject=subject,
        body=body,
        diagnostics=diagnostics,
    )


__all__ = [
    "dispatch_voice_alert",
    "dispatch_warning_email",
    "get_available_crews_tool",
    "get_daily_wind_forecast",
    "get_turbine_location",
    "get_turbines_needing_attention",
    "predict_wind_power_mwh",
]
