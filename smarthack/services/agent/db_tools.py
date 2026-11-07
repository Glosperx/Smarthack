"""
# Supabase-backed agent tools

Data tools for the dispatch agent that read the `employees`, `turbine`, `park` tables and the
`upward_turbine_mentenance` view through the Supabase REST API.

The following can be imported from this module:
- `db_get_available_crews`
- `db_get_turbine_location`
- `db_get_turbines_needing_attention`
"""

from datetime import date
import logging
import re
from typing import Any

from smarthack.clients.supabase import select_rows

logger = logging.getLogger(__name__)

_SEVERITY = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
_REPAIR_STATUSES = {"WARNING", "CRITICAL"}
_DEFAULT_CAPACITY_KW = 2050.0
_ACTIONS = {
    "CRITICAL": "Dispatch crew immediately and inspect {sub}.",
    "WARNING": "Schedule maintenance of {sub} within the week.",
    "WATCH": "Monitor {sub} on the next inspection round.",
}


def _park_filter(park_id: str | None) -> dict[str, str]:
    """
    Build the PostgREST filter for a park, tolerating non-numeric ids.

    :param park_id: Park identifier, or None for no filter.

    :returns params: Filter params; one matching no row when `park_id` is not an integer.
    """
    if not park_id:
        return {}
    if str(park_id).isdigit():
        return {"park_id": f"eq.{int(park_id)}"}
    return {"park_id": "eq.-1"}


def db_get_turbines_needing_attention(park_id: str | None = None) -> list[dict[str, Any]]:
    """
    Aggregate upcoming non-normal maintenance predictions into one triage item per turbine.

    :param park_id: Optional park id to restrict the scan.

    :returns candidates: Triage dicts for turbines in WARNING or CRITICAL state.
    :raises httpx.HTTPError: When Supabase rejects the request.
    """
    rows = select_rows(
        "upward_turbine_mentenance", {**_park_filter(park_id), "order": "predicted_date.asc"}
    )
    by_turbine: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_turbine.setdefault(int(row["turbine_id"]), []).append(row)

    today = date.today()
    items: list[dict[str, Any]] = []
    for turbine_id, entries in by_turbine.items():
        status = max((str(e["status"]).upper() for e in entries), key=lambda s: _SEVERITY.get(s, 0))
        first = next(e for e in entries if str(e["status"]).upper() == status)
        sub = str(first["suspected_subsystem"])
        days = max((date.fromisoformat(str(first["predicted_date"])) - today).days, 0)
        items.append(
            {
                "turbine_id": turbine_id,
                "park_id": str(first["park_id"]),
                "health_status": status,
                "fault_probability": max(float(e["cumulative_fault_probability"]) for e in entries),
                "days_to_failure": float(days),
                "suspected_failure": sub,
                "subsystem_risks": {
                    str(e["suspected_subsystem"]): float(e["daily_fault_probability"])
                    for e in entries
                },
                "daily_forecast": [
                    {
                        "date": str(e["predicted_date"]),
                        "status": e["status"],
                        "daily_fault_probability": e["daily_fault_probability"],
                        "cumulative_fault_probability": e["cumulative_fault_probability"],
                        "suspected_subsystem": e["suspected_subsystem"],
                    }
                    for e in entries
                ],
                "recommended_action": _ACTIONS.get(status, "No action needed.").format(sub=sub),
                "needs_repair": status in _REPAIR_STATUSES,
            }
        )
    items.sort(key=lambda i: (-_SEVERITY.get(i["health_status"], 0), i["days_to_failure"]))
    return [i for i in items if i["needs_repair"]]


def db_get_available_crews(park_id: str) -> list[dict[str, Any]]:
    """
    Read the employees assigned to a park as crew dicts, managers first.

    :param park_id: Park identifier (numeric `park.id`).

    :returns crews: Dicts with `crew_id`, `crew_name`, `park_id`, `contact_phone`,
        `contact_email`, `is_manager`, `status` and `specialties`.
    :raises httpx.HTTPError: When Supabase rejects the request.
    """
    rows = select_rows("employees", {**_park_filter(park_id), "order": "is_manager.desc,id.asc"})
    return [
        {
            "crew_id": str(r["id"]),
            "crew_name": r["full_nama"],
            "park_id": str(r["park_id"]),
            "contact_phone": r["phone_number"],
            "contact_email": r["email"],
            "is_manager": bool(r.get("is_manager")),
            "status": "AVAILABLE",
            "specialties": [],
        }
        for r in rows
    ]


def _parse_point(location: Any) -> tuple[float, float] | None:
    """
    Extract (latitude, longitude) from a PostgREST geography value.

    :param location: GeoJSON dict, or WKT / EWKT string.

    :returns coords: `(lat, lon)` or None when unparseable.
    """
    if isinstance(location, dict) and location.get("coordinates"):
        lon, lat = location["coordinates"][:2]
        return float(lat), float(lon)
    if isinstance(location, str):
        m = re.search(r"POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", location, re.IGNORECASE)
        if m:
            return float(m.group(2)), float(m.group(1))
    return None


def db_get_turbine_location(turbine_id: int) -> dict[str, Any] | None:
    """
    Resolve a turbine's coordinates from its park's location.

    :param turbine_id: `turbine.id`.

    :returns info: Dict with `latitude`, `longitude`, `capacity_kw`, or None if unknown.
    :raises httpx.HTTPError: When Supabase rejects the request.
    """
    turbines = select_rows("turbine", {"id": f"eq.{int(turbine_id)}"})
    if not turbines:
        return None
    parks = select_rows("park", {"id": f"eq.{turbines[0]['park_id']}"})
    coords = _parse_point(parks[0].get("location")) if parks else None
    if coords is None:
        logger.warning("No parsable location for turbine %s", turbine_id)
        return None
    return {"latitude": coords[0], "longitude": coords[1], "capacity_kw": _DEFAULT_CAPACITY_KW}


__all__ = [
    "db_get_available_crews",
    "db_get_turbine_location",
    "db_get_turbines_needing_attention",
]
