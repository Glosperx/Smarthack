"""
# Oversize transport network schemas

Summary of the built oversize transport network: the vehicle it was judged for, the entry
ports, how many kilometres fall under each verdict and each reason, and the sources.

The road geometry itself is served as a compact JSON file (`GET /api/transport/network`),
not through these models: it is several megabytes of coordinates.

The following can be imported from this module:
- `TransportPort`
- `TransportReasonStat`
- `TransportSource`
- `TransportSummary`
- `TransportVehicle`
- `TransportVerdictStat`
"""

from datetime import datetime

from pydantic import BaseModel, Field


class TransportVehicle(BaseModel):
    """The reference oversize load every road is judged for."""

    description: str = Field(description="What the profile represents.")
    length_m: float = Field(description="Vehicle length with the blade, metres.")
    height_m: float = Field(description="Loaded height, metres.")
    width_m: float = Field(description="Loaded width, metres.")
    gross_t: float = Field(description="Gross weight of the heaviest transport, tonnes.")


class TransportPort(BaseModel):
    """An entry point of turbine components."""

    name: str = Field(description="Port name.")
    latitude: float = Field(description="Latitude, WGS84.")
    longitude: float = Field(description="Longitude, WGS84.")


class TransportVerdictStat(BaseModel):
    """Kilometres of road under one verdict."""

    code: int = Field(description="Verdict code used in the network file.")
    label: str = Field(description="What the verdict means.")
    km: float = Field(description="Road length under this verdict, km.")


class TransportReasonStat(BaseModel):
    """Kilometres of road raising one reason."""

    bit: int = Field(description="Reason bit used in the network file.")
    label: str = Field(description="What the reason means.")
    blocking: bool = Field(description="Whether the reason blocks the road on its own.")
    km: float = Field(description="Road length raising this reason, km.")


class TransportSource(BaseModel):
    """A dataset the network is built from."""

    name: str = Field(description="Dataset name.")
    url: str = Field(description="Where it comes from.")
    license: str = Field(description="Licence and attribution.")


class TransportSummary(BaseModel):
    """What the built network is, and how its kilometres split."""

    generated_at: datetime = Field(description="When the network was built, UTC.")
    osm_extract_date: datetime | None = Field(description="Date of the OSM extract used.")
    vehicle: TransportVehicle = Field(description="The reference vehicle.")
    ports: list[TransportPort] = Field(description="Entry ports the reachability starts from.")
    classes: list[str] = Field(description="OSM road classes, index = class code.")
    verdicts: list[TransportVerdictStat] = Field(description="Kilometres per verdict.")
    reasons: list[TransportReasonStat] = Field(description="Kilometres per reason.")
    road_count: int = Field(description="Number of drawn road pieces.")
    total_km: float = Field(description="Total length of the kept roads, km.")
    caveats: list[str] = Field(description="What the network cannot tell.")
    sources: list[TransportSource] = Field(description="Datasets used.")


__all__ = [
    "TransportPort",
    "TransportReasonStat",
    "TransportSource",
    "TransportSummary",
    "TransportVehicle",
    "TransportVerdictStat",
]
