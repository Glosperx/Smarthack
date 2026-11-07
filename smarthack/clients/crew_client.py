"""
# Maintenance crew management client

Client for tracking field maintenance crew availability, assignments, and park associations.

The following can be imported from this module:
- `CrewClient`
- `get_default_crew_client`
"""

import copy
import logging

from smarthack.schemas.dispatch import CrewStatus, MaintenanceCrew

logger = logging.getLogger(__name__)

# Default seed crews across wind parks
DEFAULT_CREWS: list[dict[str, object]] = [
    {
        "crew_id": "crew_a1",
        "crew_name": "Alpha Response Team",
        "park_id": "wind_farm_a",
        "contact_phone": "+1-555-0101",
        "contact_email": "alpha.crew@windfarma.com",
        "status": CrewStatus.AVAILABLE,
        "specialties": ["Mechanical", "Drive Train", "Bearings"],
    },
    {
        "crew_id": "crew_a2",
        "crew_name": "Beta Response Team",
        "park_id": "wind_farm_a",
        "contact_phone": "+1-555-0102",
        "contact_email": "beta.crew@windfarma.com",
        "status": CrewStatus.AVAILABLE,
        "specialties": ["Electrical", "Transformers", "Generators"],
    },
    {
        "crew_id": "crew_b1",
        "crew_name": "Gamma Response Team",
        "park_id": "wind_farm_b",
        "contact_phone": "+1-555-0201",
        "contact_email": "gamma.crew@windfarmb.com",
        "status": CrewStatus.AVAILABLE,
        "specialties": ["Hydraulics", "Pitch Control", "Mechanical"],
    },
]


class CrewClient:
    """
    Client managing maintenance crew status and wind park assignments.

    Provides registry querying and status updates for park-scoped maintenance teams.
    """

    def __init__(self, initial_crews: list[MaintenanceCrew] | None = None) -> None:
        """
        Initialize the crew registry.

        :param initial_crews: Optional list of MaintenanceCrew instances. Defaults to seed data.
        """
        self._crews: dict[str, MaintenanceCrew] = {}
        if initial_crews is not None:
            for crew in initial_crews:
                self._crews[crew.crew_id] = copy.deepcopy(crew)
        else:
            self.reset_crews()

    def reset_crews(self) -> None:
        """
        Reset the crew registry to the default initial fleet state.
        """
        self._crews.clear()
        for c in DEFAULT_CREWS:
            crew = MaintenanceCrew.model_validate(c)
            self._crews[crew.crew_id] = crew

    def get_all_crews(self) -> list[MaintenanceCrew]:
        """
        Retrieve all registered maintenance crews across all wind parks.

        :returns crews: List of all MaintenanceCrew objects.
        """
        return list(self._crews.values())

    def get_crews_by_park(
        self, park_id: str, status: CrewStatus | None = None
    ) -> list[MaintenanceCrew]:
        """
        Retrieve maintenance crews dedicated to a specific wind park.

        :param park_id: The wind park identifier to filter by.
        :param status: Optional filter for crew operational status.

        :returns crews: List of matching MaintenanceCrew objects.
        """
        matched: list[MaintenanceCrew] = []
        for crew in self._crews.values():
            if crew.park_id == park_id:
                if status is None or crew.status == status:
                    matched.append(crew)
        return matched

    def get_crew(self, crew_id: str) -> MaintenanceCrew | None:
        """
        Look up a maintenance crew by its unique identifier.

        :param crew_id: Unique crew identifier.

        :returns crew: The MaintenanceCrew instance or None if not found.
        """
        return self._crews.get(crew_id)

    def update_crew_status(self, crew_id: str, status: CrewStatus) -> MaintenanceCrew | None:
        """
        Update the availability status of a designated crew.

        :param crew_id: Unique crew identifier.
        :param status: The new operational CrewStatus.

        :returns crew: The updated MaintenanceCrew instance or None if not found.
        """
        crew = self._crews.get(crew_id)
        if crew is None:
            logger.warning("Attempted to update non-existent crew ID: %s", crew_id)
            return None
        updated = crew.model_copy(update={"status": status})
        self._crews[crew_id] = updated
        logger.info("Updated crew %s (%s) status to %s", crew.crew_name, crew_id, status.value)
        return updated


_GLOBAL_CREW_CLIENT: CrewClient | None = None


def get_default_crew_client() -> CrewClient:
    """
    Return or initialize the singleton default CrewClient instance.

    :returns client: Active CrewClient instance.
    """
    global _GLOBAL_CREW_CLIENT
    if _GLOBAL_CREW_CLIENT is None:
        _GLOBAL_CREW_CLIENT = CrewClient()
    return _GLOBAL_CREW_CLIENT


__all__ = ["CrewClient", "get_default_crew_client"]
