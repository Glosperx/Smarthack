"""
# Example schema

Request and response models for the example feature routes.

The following can be imported from this module:
- `ExampleResult`
"""

from pydantic import BaseModel, Field


class ExampleResult(BaseModel):
    """
    Result model for the example query endpoint.

    Carries the echoed query and a list of matched item strings.
    """

    query: str = Field(description="The input search query echoed back.")
    items: list[str] = Field(default_factory=list, description="Matched items or results.")


__all__ = ["ExampleResult"]
