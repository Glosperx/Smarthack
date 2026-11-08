"""
Compact the Kelmarsh v4 SCADA CSVs into one parquet: one row per turbine and 10-minute slot.

Keeps the timestamp, the energy exported in the slot (kWh), the mean power (kW) and
the wind speed (m/s). Run: python -I prepare_data.py <extracted dir> <output parquet>.
"""

import re
import sys
from pathlib import Path

import polars as pl

COLUMNS = {
    "# Date and time": "Timestamp",
    "Energy Export (kWh)": "Energy_kWh",
    "Power (kW)": "Power_kW",
    "Wind speed (m/s)": "Wind_ms",
}


def main(root: Path, out: Path) -> None:
    frames = []
    for path in sorted(root.glob("Kelmarsh_SCADA_*/Turbine_Data_Kelmarsh_*.csv")):
        turbine = f"T{int(re.search(r'Turbine_Data_Kelmarsh_(\d)_', path.name).group(1)):02d}"
        frame = (
            pl.read_csv(
                path, skip_rows=9, columns=list(COLUMNS), null_values=["NaN"],
                schema_overrides={
                    "# Date and time": pl.String,
                    "Energy Export (kWh)": pl.Float64,
                    "Power (kW)": pl.Float64,
                    "Wind speed (m/s)": pl.Float64,
                },
            )
            .rename(COLUMNS)
            .with_columns(
                pl.col("Timestamp").str.to_datetime("%Y-%m-%d %H:%M:%S"),
                pl.lit(turbine).alias("Turbine_ID"),
            )
            .select("Turbine_ID", "Timestamp", "Energy_kWh", "Power_kW", "Wind_ms")
            # The 2023-2024 exports pad each file with ~2.1M all-null rows (many repeating
            # one timestamp) around the ~52.7k real 10-minute rows; a missing slot is a gap.
            .filter(
                pl.col("Energy_kWh").is_not_null()
                | pl.col("Power_kW").is_not_null()
                | pl.col("Wind_ms").is_not_null()
            )
        )
        frames.append(frame)
        print(path.name, frame.height, flush=True)
    table = pl.concat(frames).sort("Turbine_ID", "Timestamp")
    table.write_parquet(out)
    print(table.shape, table.get_column("Timestamp").min(), table.get_column("Timestamp").max())


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
