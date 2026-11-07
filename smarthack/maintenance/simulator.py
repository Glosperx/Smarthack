"""
# SCADA telemetry simulator

Generation and replay of streaming wind turbine telemetry with fault injection scenarios.

The following can be imported from this module:
- `ScadaSimulator`
- `simulate_telemetry_stream`
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from smarthack.maintenance.constants import (
    DEFAULT_SCADA_SAMPLE_MINUTES,
    SCENARIO_BEARING_OVERHEATING,
    SCENARIO_GEARBOX_WEAR,
    SCENARIO_HYDRAULIC_LEAK,
    SCENARIO_NORMAL,
    SCENARIO_TRANSFORMER_OVERHEATING,
    SENSOR_AMBIENT_TEMP,
    SENSOR_BEARING_DE,
    SENSOR_BEARING_NDE,
    SENSOR_GEARBOX_BEARING,
    SENSOR_GEARBOX_OIL,
    SENSOR_GENERATOR_RPM,
    SENSOR_GRID_POWER,
    SENSOR_HYDRAULIC_OIL,
    SENSOR_NACELLE_TEMP,
    SENSOR_PITCH_ANGLE,
    SENSOR_ROTOR_RPM,
    SENSOR_STATOR_PHASE1,
    SENSOR_STATOR_PHASE2,
    SENSOR_STATOR_PHASE3,
    SENSOR_TRANSFORMER_L1,
    SENSOR_TRANSFORMER_L2,
    SENSOR_TRANSFORMER_L3,
    SENSOR_WIND_SPEED,
)


class ScadaSimulator:
    """Wind turbine operational telemetry generator with scenario-based fault injection."""

    def __init__(self, seed: int | None = 42) -> None:
        """
        Initialize the simulator with an optional random seed.

        :param seed: Random seed for reproducible telemetry simulation.
        """
        self.rng = np.random.default_rng(seed)

    def generate_stream(
        self,
        asset_id: int = 0,
        duration_hours: int = 48,
        scenario: str = SCENARIO_NORMAL,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        """
        Synthesize a realistic 10-minute SCADA observation time-series.

        :param asset_id: Identifier of the wind turbine asset.
        :param duration_hours: Duration of the telemetry window in hours.
        :param scenario: Fault profile (`normal`, `bearing_overheating`, `gearbox_wear`, etc.).
        :param end_time: Timestamp of the most recent record. Defaults to now.

        :returns telemetry_df: DataFrame with 10-minute SCADA intervals and sensor readings.
        """
        if end_time is None:
            end_time = datetime.now()

        num_intervals = int(duration_hours * 60 / DEFAULT_SCADA_SAMPLE_MINUTES)
        num_intervals = max(num_intervals, 6)

        start_time = end_time - timedelta(
            minutes=(num_intervals - 1) * DEFAULT_SCADA_SAMPLE_MINUTES
        )
        timestamps = [
            start_time + timedelta(minutes=i * DEFAULT_SCADA_SAMPLE_MINUTES)
            for i in range(num_intervals)
        ]

        t_fraction = np.linspace(0.0, 1.0, num_intervals)

        # Baseline environmental signals
        diurnal_cycle = np.sin(2.0 * np.pi * t_fraction * (duration_hours / 24.0))
        ambient_temp = 18.0 + 5.0 * diurnal_cycle + self.rng.normal(0.0, 0.8, num_intervals)
        ambient_temp = np.clip(ambient_temp, 5.0, 42.0)

        # Wind speed varying between 3 and 14 m/s
        wind_speed = (
            7.5
            + 3.0 * np.sin(2.0 * np.pi * t_fraction * (duration_hours / 12.0))
            + self.rng.normal(0.0, 1.2, num_intervals)
        )
        wind_speed = np.clip(wind_speed, 1.0, 22.0)

        # Active power follows standard cubic transition
        power_norm = np.clip((wind_speed - 3.0) / (12.5 - 3.0), 0.0, 1.0) ** 3
        power_kw = power_norm * 2000.0 + self.rng.normal(0.0, 20.0, num_intervals)
        power_kw = np.clip(power_kw, 0.0, 2050.0)

        # Generator & rotor rotational speeds
        rpm = np.clip(
            800.0 + wind_speed * 70.0 + self.rng.normal(0.0, 15.0, num_intervals),
            0.0,
            1650.0,
        )
        rotor_rpm = (rpm / 100.0) + self.rng.normal(0.0, 0.1, num_intervals)
        pitch = np.where(wind_speed > 12.5, (wind_speed - 12.5) * 1.8, 0.0)
        nacelle_temp = ambient_temp + 12.0 + (power_kw / 2000.0) * 4.0

        # Normal component thermal baselines
        load_factor = power_kw / 2000.0
        bearing_de = (
            ambient_temp + 22.0 + load_factor * 8.0 + self.rng.normal(0.0, 1.0, num_intervals)
        )
        bearing_nde = (
            ambient_temp + 19.0 + load_factor * 6.0 + self.rng.normal(0.0, 0.9, num_intervals)
        )
        gearbox_bearing = (
            ambient_temp + 26.0 + load_factor * 10.0 + self.rng.normal(0.0, 1.1, num_intervals)
        )
        gearbox_oil = (
            ambient_temp + 24.0 + load_factor * 8.0 + self.rng.normal(0.0, 0.8, num_intervals)
        )
        hydraulic_oil = (
            ambient_temp + 18.0 + load_factor * 5.0 + self.rng.normal(0.0, 0.7, num_intervals)
        )
        trans_base = ambient_temp + 35.0 + load_factor * 12.0
        trans_l1 = trans_base + self.rng.normal(0.0, 1.0, num_intervals)
        trans_l2 = trans_base + 1.5 + self.rng.normal(0.0, 1.0, num_intervals)
        trans_l3 = trans_base - 1.0 + self.rng.normal(0.0, 1.0, num_intervals)

        stator_base = ambient_temp + 30.0 + load_factor * 10.0
        stator_p1 = stator_base + self.rng.normal(0.0, 0.8, num_intervals)
        stator_p2 = stator_base + 0.5 + self.rng.normal(0.0, 0.8, num_intervals)
        stator_p3 = stator_base - 0.5 + self.rng.normal(0.0, 0.8, num_intervals)

        # Scenario fault injections
        if scenario == SCENARIO_BEARING_OVERHEATING:
            # Over the last half of the window, ramp up drive-end bearing temperature to ~92°C
            degradation_ramp = np.clip((t_fraction - 0.4) / 0.6, 0.0, 1.0) ** 1.8
            bearing_de = (
                bearing_de
                + degradation_ramp * 44.0
                + degradation_ramp * self.rng.normal(0.0, 3.0, num_intervals)
            )

        elif scenario == SCENARIO_GEARBOX_WEAR:
            # High-speed shaft and oil temperatures elevate significantly
            degradation_ramp = np.clip((t_fraction - 0.3) / 0.7, 0.0, 1.0) ** 1.5
            gearbox_bearing = (
                gearbox_bearing + degradation_ramp * 32.0 + self.rng.normal(0.0, 2.0, num_intervals)
            )
            gearbox_oil = gearbox_oil + degradation_ramp * 26.0

        elif scenario == SCENARIO_HYDRAULIC_LEAK:
            # Hydraulic oil temperature climbs above safe threshold
            degradation_ramp = np.clip((t_fraction - 0.35) / 0.65, 0.0, 1.0) ** 1.4
            hydraulic_oil = (
                hydraulic_oil + degradation_ramp * 28.0 + self.rng.normal(0.0, 1.5, num_intervals)
            )
            pitch = pitch + degradation_ramp * self.rng.normal(0.0, 3.5, num_intervals)

        elif scenario == SCENARIO_TRANSFORMER_OVERHEATING:
            # Transformer temperature surges to ~110°C with severe inter-phase divergence
            degradation_ramp = np.clip((t_fraction - 0.3) / 0.7, 0.0, 1.0) ** 1.6
            trans_l1 = trans_l1 + degradation_ramp * 30.0
            trans_l2 = trans_l2 + degradation_ramp * 48.0 + self.rng.normal(0.0, 2.5, num_intervals)
            trans_l3 = trans_l3 + degradation_ramp * 58.0 + self.rng.normal(0.0, 3.0, num_intervals)

        return pd.DataFrame(
            {
                "time_stamp": timestamps,
                "asset_id": asset_id,
                SENSOR_AMBIENT_TEMP: np.round(ambient_temp, 2),
                SENSOR_WIND_SPEED: np.round(wind_speed, 2),
                SENSOR_PITCH_ANGLE: np.round(pitch, 2),
                SENSOR_GENERATOR_RPM: np.round(rpm, 1),
                SENSOR_ROTOR_RPM: np.round(rotor_rpm, 2),
                SENSOR_GRID_POWER: np.round(power_kw, 1),
                SENSOR_BEARING_DE: np.round(bearing_de, 2),
                SENSOR_BEARING_NDE: np.round(bearing_nde, 2),
                SENSOR_GEARBOX_BEARING: np.round(gearbox_bearing, 2),
                SENSOR_GEARBOX_OIL: np.round(gearbox_oil, 2),
                SENSOR_HYDRAULIC_OIL: np.round(hydraulic_oil, 2),
                SENSOR_TRANSFORMER_L1: np.round(trans_l1, 2),
                SENSOR_TRANSFORMER_L2: np.round(trans_l2, 2),
                SENSOR_TRANSFORMER_L3: np.round(trans_l3, 2),
                SENSOR_STATOR_PHASE1: np.round(stator_p1, 2),
                SENSOR_STATOR_PHASE2: np.round(stator_p2, 2),
                SENSOR_STATOR_PHASE3: np.round(stator_p3, 2),
                SENSOR_NACELLE_TEMP: np.round(nacelle_temp, 2),
                "scenario": scenario,
            }
        )


def simulate_telemetry_stream(
    asset_id: int = 0,
    duration_hours: int = 48,
    scenario: str = SCENARIO_NORMAL,
    seed: int | None = 42,
) -> pd.DataFrame:
    """
    Generate streaming SCADA telemetry records for a specified scenario.

    :param asset_id: Wind turbine identifier.
    :param duration_hours: Length of time in hours to simulate.
    :param scenario: Fault profile to simulate.
    :param seed: Random seed.

    :returns df: Synthesized telemetry records.
    """
    simulator = ScadaSimulator(seed=seed)
    return simulator.generate_stream(
        asset_id=asset_id,
        duration_hours=duration_hours,
        scenario=scenario,
    )


__all__ = ["ScadaSimulator", "simulate_telemetry_stream"]
