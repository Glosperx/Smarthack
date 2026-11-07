"""
Download ERA5 100 m wind (u and v components) for Romania, one NetCDF file per year.

Needs `pip install "cdsapi>=0.7.2"` and a `~/.cdsapirc` file with the Copernicus CDS
url and key. Files land in `.data/era5/` (git-ignored). Years already downloaded are
skipped, so the script can be stopped and run again.

Usage: python scripts/download_era5.py
"""

import os

import cdsapi

OUT_DIR = ".data/era5"
FIRST_YEAR = 2016
LAST_YEAR = 2025

# North, West, South, East: a box around Romania.
AREA = [48.5, 20, 43.5, 30]

# If the form only offered 10 m winds, use "10m_u_component_of_wind" and
# "10m_v_component_of_wind" here instead.
VARIABLES = ["100m_u_component_of_wind", "100m_v_component_of_wind"]


def main() -> None:
    """Request each year from the CDS and save it under `OUT_DIR`."""
    os.makedirs(OUT_DIR, exist_ok=True)
    client = cdsapi.Client()

    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        target = f"{OUT_DIR}/era5_wind100m_{year}.nc"
        if os.path.exists(target):
            print(f"{year}: already downloaded, skipping")
            continue
        print(f"{year}: requesting (it may wait in the queue for a while)...")
        client.retrieve(
            "reanalysis-era5-single-levels",
            {
                "product_type": "reanalysis",
                "variable": VARIABLES,
                "year": str(year),
                "month": [f"{m:02d}" for m in range(1, 13)],
                "day": [f"{d:02d}" for d in range(1, 32)],
                "time": [f"{h:02d}:00" for h in range(24)],
                "area": AREA,
                "data_format": "netcdf",
                "download_format": "unarchived",
            },
            target,
        )
        print(f"{year}: saved to {target}")


if __name__ == "__main__":
    main()
