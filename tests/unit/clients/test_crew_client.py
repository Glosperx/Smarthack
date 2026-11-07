"""
# Unit tests for maintenance crew client

Validates crew registration, wind park filtering, and status updates.
"""

from smarthack.clients.crew_client import CrewClient, get_default_crew_client
from smarthack.schemas.dispatch import CrewStatus, MaintenanceCrew


def test_crew_client_defaults() -> None:
    """Verify default initial crew registry population."""
    client = CrewClient()
    crews = client.get_all_crews()
    assert len(crews) >= 3

    park_a_crews = client.get_crews_by_park("wind_farm_a")
    assert len(park_a_crews) == 2
    assert all(c.park_id == "wind_farm_a" for c in park_a_crews)

    park_b_crews = client.get_crews_by_park("wind_farm_b")
    assert len(park_b_crews) == 1
    assert park_b_crews[0].park_id == "wind_farm_b"


def test_crew_client_status_update() -> None:
    """Verify operational status updates for a designated crew."""
    client = CrewClient()
    updated = client.update_crew_status("crew_a1", CrewStatus.DISPATCHED)
    assert updated is not None
    assert updated.status == CrewStatus.DISPATCHED

    available = client.get_crews_by_park("wind_farm_a", status=CrewStatus.AVAILABLE)
    assert len(available) == 1
    assert available[0].crew_id == "crew_a2"

    # Non-existent crew
    assert client.update_crew_status("non_existent", CrewStatus.DISPATCHED) is None


def test_crew_client_custom_init() -> None:
    """Verify custom initial crew seeding."""
    custom_crew = MaintenanceCrew(
        crew_id="test_c1",
        crew_name="Test Crew",
        park_id="wind_farm_c",
        contact_phone="+1-555-9999",
        contact_email="test@parkc.com",
        status=CrewStatus.AVAILABLE,
        specialties=["Electrical"],
    )
    client = CrewClient([custom_crew])
    assert len(client.get_all_crews()) == 1
    assert client.get_crew("test_c1") is not None


def test_default_crew_client_singleton() -> None:
    """Verify singleton accessor."""
    c1 = get_default_crew_client()
    c2 = get_default_crew_client()
    assert c1 is c2
