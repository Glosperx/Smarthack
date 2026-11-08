"""
# Upstream clients

Thin async client wrappers over external APIs, local services, and file sources.
Clients take an `httpx.AsyncClient` or path and return validated schema models.

The following can be imported from this module:
- `CrewClient`
- `DecisionClient`
- `DecisionModelError`
- `EmailNotificationClient`
- `VoiceNotificationClient`
- `fetch_example`
- `fetch_maintenance_inputs`
- `fetch_parks`
- `fetch_turbines_with_predictions`
- `get_data_file_path`
- `get_default_crew_client`
- `get_default_decision_client`
- `get_default_email_client`
- `get_default_voice_client`
"""

from smarthack.clients.crew_client import CrewClient, get_default_crew_client
from smarthack.clients.decision_client import (
    DecisionClient,
    DecisionModelError,
    get_default_decision_client,
)
from smarthack.clients.email_client import EmailNotificationClient, get_default_email_client
from smarthack.clients.example_service import fetch_example, get_data_file_path
from smarthack.clients.supabase import (
    fetch_maintenance_inputs,
    fetch_parks,
    fetch_turbines_with_predictions,
)
from smarthack.clients.voice_client import VoiceNotificationClient, get_default_voice_client

__all__ = [
    "CrewClient",
    "DecisionClient",
    "DecisionModelError",
    "EmailNotificationClient",
    "VoiceNotificationClient",
    "fetch_example",
    "fetch_maintenance_inputs",
    "fetch_parks",
    "fetch_turbines_with_predictions",
    "get_data_file_path",
    "get_default_crew_client",
    "get_default_decision_client",
    "get_default_email_client",
    "get_default_voice_client",
]
