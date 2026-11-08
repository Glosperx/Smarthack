"""
Build the oversize transport network: every major road judged for a wind turbine convoy.

Downloads the OpenStreetMap extract of Romania on the first run (about 330 MB, cached in
TRANSPORT_CACHE_DIR), then writes the network to TRANSPORT_NETWORK_DIR. A rebuild from
the cache takes a few minutes.

Usage: python scripts/build_transport.py [--refresh] [--pbf PATH]
"""

import argparse
import logging
from pathlib import Path

from smarthack.services.transport_service import build_network
from smarthack.utils.logging_utils import configure_logging


def main() -> None:
    """Parse the arguments, build the network and print its headline numbers."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--refresh", action="store_true", help="download a fresh OSM extract")
    parser.add_argument("--pbf", type=Path, default=None, help="use this .osm.pbf instead")
    args = parser.parse_args()
    configure_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    summary = build_network(pbf=args.pbf, refresh=args.refresh)
    v = summary.vehicle
    print(
        f"Vehicle          {v.length_m:.0f} m long, {v.height_m} m high, "
        f"{v.width_m} m wide, {v.gross_t:.0f} t"
    )
    print(f"Ports            {', '.join(p.name for p in summary.ports)}")
    print(f"Roads judged     {summary.total_km:,.0f} km in {summary.road_count:,} pieces")
    for stat in summary.verdicts:
        share = stat.km / summary.total_km if summary.total_km else 0.0
        print(f"  {stat.km:>9,.0f} km  {share:6.1%}  {stat.label}")
    print("Reasons (km)")
    for reason in sorted(summary.reasons, key=lambda r: -r.km):
        if reason.km > 0:
            mark = "x" if reason.blocking else " "
            print(f"  {mark} {reason.km:>9,.0f}  {reason.label}")


if __name__ == "__main__":
    main()
