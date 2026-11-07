"""
CLI script to run wind turbine power forecasts for any GPS coordinates.
"""

import argparse
import sys

from smarthack.wind.agent_tool import format_forecast_table, predict_wind_power
from smarthack.wind.constants import (
    DEFAULT_FORECAST_DAYS,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_TURBINE_CAPACITY_KW,
)


def main() -> int:
    """
    Execute CLI wind prediction tool.

    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Forecast Wind Turbine Power Generation")
    parser.add_argument("--lat", type=float, default=DEFAULT_LATITUDE, help="Latitude of site")
    parser.add_argument("--lon", type=float, default=DEFAULT_LONGITUDE, help="Longitude of site")
    parser.add_argument(
        "--days", type=int, default=DEFAULT_FORECAST_DAYS, help="Forecast horizon (days)"
    )
    parser.add_argument(
        "--capacity-kw", type=float, default=DEFAULT_TURBINE_CAPACITY_KW, help="Capacity in kW"
    )
    parser.add_argument(
        "--single-model", action="store_true", help="Use single model instead of Tri-Ensemble"
    )
    args = parser.parse_args()

    print(f"\nFetching forecast for ({args.lat}, {args.lon}) over {args.days} days...")
    try:
        result = predict_wind_power(
            latitude=args.lat,
            longitude=args.lon,
            forecast_days=args.days,
            capacity_kw=args.capacity_kw,
            use_ensemble=not args.single_model,
        )
    except Exception as exc:
        print(f"Error during forecast: {exc}", file=sys.stderr)
        return 1

    print("\n" + result["summary_text"] + "\n")
    print(format_forecast_table(result, max_rows=24))
    return 0


if __name__ == "__main__":
    sys.exit(main())
