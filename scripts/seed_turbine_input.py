"""
Seed mock SCADA telemetry features into Supabase table `turbine_maintenance_input`.

Generates physically consistent observations (temperatures, vibrations, kinematics)
matching the 29 features required by the predictive maintenance model, linked to
real turbine IDs across registered wind parks.

Usage:
    python scripts/seed_turbine_input.py --push
    python scripts/seed_turbine_input.py --print-sql
"""

import argparse
import sys
from typing import Any

from dotenv import load_dotenv
import httpx

from smarthack import config
from smarthack.maintenance.features import extract_maintenance_features
from smarthack.maintenance.simulator import ScadaSimulator

load_dotenv(".env")

# Map turbine IDs to realistic operational profiles
# Turbines 1-3 (Park 1), 4-5 (Park 2), 6-8 (Park 3), 9-10 (Park 4), 11-12 (Park 5)
TURBINE_PROFILES: list[dict[str, Any]] = [
    {
        "turbine_id": 1,
        "scenario": "bearing_overheating",
        "desc": "Critical Drive-End Bearing Overheating",
        "count": 3,
    },
    {"turbine_id": 2, "scenario": "normal", "desc": "Healthy Baseline Operation", "count": 3},
    {
        "turbine_id": 3,
        "scenario": "hydraulic_leak",
        "desc": "Hydraulic Pitch Pressure Drop",
        "count": 2,
    },
    {
        "turbine_id": 4,
        "scenario": "gearbox_wear",
        "desc": "Gearbox Bearing & Oil Degradation",
        "count": 2,
    },
    {"turbine_id": 5, "scenario": "normal", "desc": "Healthy Baseline Operation", "count": 2},
    {
        "turbine_id": 6,
        "scenario": "transformer_overheating",
        "desc": "Transformer 3-Phase Severe Imbalance",
        "count": 2,
    },
    {"turbine_id": 7, "scenario": "normal", "desc": "Healthy Baseline Operation", "count": 2},
    {"turbine_id": 8, "scenario": "normal", "desc": "Healthy Baseline Operation", "count": 2},
    {
        "turbine_id": 9,
        "scenario": "bearing_overheating",
        "desc": "Early Bearing Temperature Drift",
        "count": 2,
    },
    {"turbine_id": 10, "scenario": "normal", "desc": "Healthy Baseline Operation", "count": 2},
    {
        "turbine_id": 11,
        "scenario": "gearbox_wear",
        "desc": "Moderate Gearbox Oil Warming",
        "count": 2,
    },
    {"turbine_id": 12, "scenario": "normal", "desc": "Healthy Baseline Operation", "count": 2},
]


def generate_mock_rows() -> list[dict[str, Any]]:
    """
    Generate realistic multi-scenario telemetry observation rows with turbine references.

    :returns rows: List of dictionaries with the 29 physical SCADA features + turbine_id.
    """
    sim = ScadaSimulator(seed=42)
    all_rows: list[dict[str, Any]] = []

    for item in TURBINE_PROFILES:
        t_id = item["turbine_id"]
        scenario = item["scenario"]
        count = item["count"]

        df_stream = sim.generate_stream(asset_id=t_id, scenario=scenario, duration_hours=48)
        feats_df = extract_maintenance_features(df_stream)
        sampled = feats_df.iloc[-count:]

        for _idx, row_series in sampled.iterrows():
            row_dict: dict[str, Any] = {
                col: round(float(val), 4) for col, val in row_series.items()
            }
            row_dict["turbine_id"] = int(t_id)
            all_rows.append(row_dict)

    return all_rows


def push_to_supabase(rows: list[dict[str, Any]]) -> None:
    """
    Post telemetry rows to the Supabase REST endpoint.

    :param rows: Telemetry feature dictionaries with turbine_id.
    """
    url = f"{config.supabase_url()}/rest/v1/turbine_maintenance_input"
    headers = {
        "apikey": config.supabase_key(),
        "Authorization": f"Bearer {config.supabase_key()}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    print(f"[*] Pushing {len(rows)} rows with turbine references to Supabase ({url})...")
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=rows, headers=headers)
        if resp.status_code in (200, 201):
            print(f"[+] Successfully inserted {len(rows)} rows into turbine_maintenance_input!")
        else:
            print(f"[!] Supabase error ({resp.status_code}): {resp.text}")
            sys.exit(1)


def print_sql(rows: list[dict[str, Any]]) -> None:
    """
    Print SQL insert statements to stdout.

    :param rows: Telemetry feature dictionaries with turbine_id.
    """
    if not rows:
        return
    cols = ", ".join(rows[0].keys())
    for r in rows:
        vals = ", ".join(str(v) for v in r.values())
        print(f"INSERT INTO turbine_maintenance_input ({cols}) VALUES ({vals});")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Seed mock telemetry data with turbine references."
    )
    parser.add_argument("--push", action="store_true", help="Directly insert rows into Supabase.")
    parser.add_argument("--print-sql", action="store_true", help="Print SQL INSERT statements.")
    args = parser.parse_args()

    rows = generate_mock_rows()
    print(f"[i] Generated {len(rows)} telemetry rows referencing {len(TURBINE_PROFILES)} turbines.")

    if args.push:
        push_to_supabase(rows)
    elif args.print_sql:
        print_sql(rows)
    else:
        print("[i] Run with --push to upload to Supabase, or --print-sql to view SQL statements.")


if __name__ == "__main__":
    main()
