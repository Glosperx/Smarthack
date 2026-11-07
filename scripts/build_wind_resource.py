"""
Build the hill-zone wind resource atlas: heatmap, candidate sites and backtest report.

Downloads NASA POWER, the Global Wind Atlas and Copernicus DEM tiles on the first run
(about 300 MB, cached in RESOURCE_CACHE_DIR), then writes the atlas to
RESOURCE_ATLAS_DIR. A rebuild from the cache takes about a minute.

Usage: python scripts/build_wind_resource.py [--no-names]
"""

import argparse
import logging

from smarthack.services.resource_service import build_atlas
from smarthack.utils.logging_utils import configure_logging


def main() -> None:
    """Parse the arguments, build the atlas and print its headline numbers."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--no-names", action="store_true", help="skip the Nominatim locality lookup for sites"
    )
    parser.add_argument("--last-year", type=int, default=None, help="last complete data year")
    args = parser.parse_args()
    configure_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    summary = build_atlas(last_year=args.last_year, name_sites=not args.no_names)
    print(f"Forecast years      {summary.target_years[0]}-{summary.target_years[1]}")
    print(f"Method (validation) {summary.selected_estimator}")
    for row in summary.backtest:
        mark = "*" if row.selected else " "
        print(
            f"  {mark} {row.estimator:18s} val MAE {row.mae_validation:.3f}  "
            f"test MAE {row.mae_test:.3f} m/s  ({row.mape_test * 100:.1f}%)"
        )
    print(
        f"P10-P90 band        {summary.band_low_pct * 100:+.1f}% / {summary.band_high_pct * 100:+.1f}%"
        f"  test coverage {summary.band_coverage_test:.0%} (nominal 80%)"
    )
    print(f"Ranking stability   Spearman {summary.rank_correlation_test:.3f}")
    print(
        f"Hill terrain        {summary.hill_area_km2:,.0f} km2, "
        f"buildable {summary.buildable_area_km2:,.0f} km2"
    )


if __name__ == "__main__":
    main()
