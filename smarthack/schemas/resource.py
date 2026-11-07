"""
# Wind resource atlas schemas

Data contracts of the hill-zone wind atlas: its summary (method, backtest, legend,
sources), the proposed park sites and the answer for a single point on the map.

The following can be imported from this module:
- `ResourceBacktestRow`
- `ResourceBounds`
- `ResourceLegend`
- `ResourcePoint`
- `ResourceSite`
- `ResourceSource`
- `ResourceSummary`
"""

from pydantic import BaseModel, Field


class ResourceBounds(BaseModel):
    """Geographic extent of the heatmap image, in WGS84 degrees."""

    south: float = Field(description="Southern edge latitude.")
    west: float = Field(description="Western edge longitude.")
    north: float = Field(description="Northern edge latitude.")
    east: float = Field(description="Eastern edge longitude.")


class ResourceLegend(BaseModel):
    """How heatmap colours map to wind speed."""

    vmin: float = Field(description="Wind speed (m/s) at the lightest colour.")
    vmax: float = Field(description="Wind speed (m/s) at the darkest colour.")
    colors: list[str] = Field(description="Hex colours from vmin to vmax, evenly spaced.")
    unit: str = Field(default="m/s", description="Unit of the legend values.")


class ResourceBacktestRow(BaseModel):
    """Out-of-sample score of one forecasting method."""

    estimator: str = Field(description="Method identifier, such as `climatology_10y`.")
    mae_validation: float = Field(description="Mean absolute error (m/s), validation period.")
    mae_test: float = Field(description="Mean absolute error (m/s), held-out test period.")
    mape_test: float = Field(description="Mean absolute percentage error, test period (0-1).")
    selected: bool = Field(description="True for the method chosen on the validation period.")


class ResourceSource(BaseModel):
    """A public dataset the atlas is built from."""

    name: str = Field(description="Dataset name.")
    role: str = Field(description="What the atlas uses it for.")
    url: str = Field(description="Where it comes from.")
    license: str = Field(description="Licence or terms of use.")


class ResourceSummary(BaseModel):
    """Everything the map needs to draw and explain the atlas."""

    target_years: list[int] = Field(description="First and last forecast year, inclusive.")
    data_until: int = Field(description="Last complete year of wind data used.")
    reference_years: list[int] = Field(description="Period of the fine-scale reference atlas.")
    bounds: ResourceBounds = Field(description="Extent of the heatmap image.")
    elevation_band_m: list[float] = Field(description="Minimum and maximum elevation shown.")
    max_slope_deg: float = Field(description="Steepest mean slope a proposed site may have.")
    legend: ResourceLegend = Field(description="Colour scale of the heatmap.")
    selected_estimator: str = Field(description="Forecast method chosen by the backtest.")
    backtest: list[ResourceBacktestRow] = Field(description="Scores of every method compared.")
    validation_years: list[int] = Field(description="Target years used to select the method.")
    test_years: list[int] = Field(description="Target years held out to report its error.")
    band_low_pct: float = Field(description="P10 as a relative deviation from P50 (e.g. -0.04).")
    band_high_pct: float = Field(description="P90 as a relative deviation from P50 (e.g. 0.03).")
    band_coverage_test: float = Field(
        description="Share of test outcomes inside the P10-P90 band (nominal 0.8)."
    )
    rank_correlation_test: float = Field(
        description="Spearman correlation between forecast and actual ranking of areas."
    )
    hill_area_km2: float = Field(description="Area of hill terrain in the elevation band.")
    buildable_area_km2: float = Field(description="Hill area that is also gentle enough.")
    hill_wind_p50_mean: float = Field(description="Mean forecast wind over all hill terrain.")
    sources: list[ResourceSource] = Field(description="Datasets used, with licences.")
    generated_at: str = Field(description="When the atlas was built (ISO 8601, UTC).")


class ResourceSite(BaseModel):
    """A proposed wind park site: the best park-sized window of its area."""

    rank: int = Field(ge=1, description="1 for the windiest proposed site.")
    name: str | None = Field(default=None, description="Nearby locality and county.")
    latitude: float = Field(ge=-90, le=90, description="Site centre latitude.")
    longitude: float = Field(ge=-180, le=180, description="Site centre longitude.")
    wind_p50: float = Field(description="Forecast mean wind at 100 m (m/s), median.")
    wind_p10: float = Field(description="Low end of the 80 % band (m/s).")
    wind_p90: float = Field(description="High end of the 80 % band (m/s).")
    reference_wind: float = Field(description="Long-term mean of the reference period (m/s).")
    change_pct: float = Field(description="Forecast relative to the reference period (0-1).")
    elevation_m: float = Field(description="Mean elevation of the site window.")
    slope_deg: float = Field(description="Mean terrain slope of the site window.")
    buildable_fraction: float = Field(description="Share of the window that is buildable hill.")
    percentile: float = Field(description="Share of hill terrain with less wind (0-100).")
    explanation: str = Field(description="Why the site was proposed, in one sentence.")


class ResourcePoint(BaseModel):
    """The atlas answer for one clicked point."""

    latitude: float = Field(description="Queried latitude.")
    longitude: float = Field(description="Queried longitude.")
    inside_country: bool = Field(description="False outside Romania (no atlas data).")
    in_band: bool = Field(description="True when the elevation is inside the hill band.")
    buildable: bool = Field(description="True when in the band and gentle enough to build on.")
    elevation_m: float | None = Field(default=None, description="Mean elevation of the cell.")
    slope_deg: float | None = Field(default=None, description="Mean slope of the cell.")
    wind_p50: float | None = Field(default=None, description="Forecast mean wind (m/s).")
    wind_p10: float | None = Field(default=None, description="Low end of the band (m/s).")
    wind_p90: float | None = Field(default=None, description="High end of the band (m/s).")
    reference_wind: float | None = Field(default=None, description="Reference-period mean.")
    change_pct: float | None = Field(default=None, description="Forecast vs reference (0-1).")
    percentile: float | None = Field(
        default=None, description="Share of hill terrain with less wind (0-100)."
    )
    explanation: str = Field(description="Plain-language reading of the numbers.")


__all__ = [
    "ResourceBacktestRow",
    "ResourceBounds",
    "ResourceLegend",
    "ResourcePoint",
    "ResourceSite",
    "ResourceSource",
    "ResourceSummary",
]
