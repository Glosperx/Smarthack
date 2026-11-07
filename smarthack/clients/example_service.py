"""
# Example client service

Outbound HTTP client wrapper for the example upstream service.

The following can be imported from this module:
- `fetch_example`
- `get_data_file_path`
"""

from pathlib import Path

import httpx

from smarthack import config
from smarthack.schemas.example import ExampleResult


async def fetch_example(http: httpx.AsyncClient, query: str) -> ExampleResult:
    """
    Fetch search results from the example upstream service.

    :param http: Shared asynchronous HTTP client.
    :param query: Search query parameter string.

    :returns result: Validated `ExampleResult` model.
    :raises httpx.HTTPError: When the upstream HTTP request fails.
    """
    url = f"{config.example_service_url()}/search"
    resp = await http.get(url, params={"q": query})
    resp.raise_for_status()
    return ExampleResult.model_validate(resp.json())


def get_data_file_path(filename: str) -> Path:
    """
    Resolve the path to a data file within the configured data directory.

    :param filename: Relative file name within the data directory.

    :returns path: Resolved Path object pointing to the target file.
    """
    return config.data_dir() / filename


__all__ = ["fetch_example", "get_data_file_path"]
