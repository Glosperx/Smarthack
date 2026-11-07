"""
# Schemas

Data contracts and transfer objects for the API, built with Pydantic.
These define the schema of requests and responses exposed via OpenAPI.

The following can be imported from this module:
- `ExampleResult`
- `Park`
"""

from smarthack.schemas.example import ExampleResult
from smarthack.schemas.parks import Park

__all__ = ["ExampleResult", "Park"]
