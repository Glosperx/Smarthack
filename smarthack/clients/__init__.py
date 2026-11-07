"""
# Upstream clients

Thin async client wrappers over external APIs, local services, and file sources.
Clients take an `httpx.AsyncClient` or path and return validated schema models.

The following can be imported from this module:
- `fetch_example`
- `fetch_parks`
- `get_data_file_path`
"""

from smarthack.clients.example_service import fetch_example, get_data_file_path
from smarthack.clients.supabase_parks import fetch_parks

__all__ = ["fetch_example", "fetch_parks", "get_data_file_path"]
