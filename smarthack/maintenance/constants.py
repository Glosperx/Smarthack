"""
# Maintenance constants

Scalars, failure scenarios, sensor mappings, and thresholds for predictive maintenance.

The following can be imported from this module:
- `DEFAULT_HEALTH_THRESHOLD_CRITICAL`
- `DEFAULT_HEALTH_THRESHOLD_WARNING`
- `DEFAULT_HEALTH_THRESHOLD_WATCH`
- `DEFAULT_MAINTENANCE_HORIZON_DAYS`
- `DEFAULT_SCADA_SAMPLE_MINUTES`
- `FAULT_SUBSYSTEMS`
- `HEALTH_STATUS_CRITICAL`
- `HEALTH_STATUS_NORMAL`
- `HEALTH_STATUS_WARNING`
- `HEALTH_STATUS_WATCH`
- `SCENARIO_BEARING_OVERHEATING`
- `SCENARIO_GEARBOX_WEAR`
- `SCENARIO_HYDRAULIC_LEAK`
- `SCENARIO_NORMAL`
- `SCENARIO_TRANSFORMER_OVERHEATING`
- `SENSOR_AMBIENT_TEMP`
- `SENSOR_BEARING_DE`
- `SENSOR_BEARING_NDE`
- `SENSOR_GEARBOX_BEARING`
- `SENSOR_GEARBOX_OIL`
- `SENSOR_GENERATOR_RPM`
- `SENSOR_GRID_POWER`
- `SENSOR_HYDRAULIC_OIL`
- `SENSOR_NACELLE_TEMP`
- `SENSOR_PITCH_ANGLE`
- `SENSOR_ROTOR_RPM`
- `SENSOR_STATOR_PHASE1`
- `SENSOR_STATOR_PHASE2`
- `SENSOR_STATOR_PHASE3`
- `SENSOR_TRANSFORMER_L1`
- `SENSOR_TRANSFORMER_L2`
- `SENSOR_TRANSFORMER_L3`
- `SENSOR_WIND_SPEED`
"""

#: SCADA column name for ambient temperature (°C).
SENSOR_AMBIENT_TEMP: str = "sensor_0_avg"

#: SCADA column name for wind speed (m/s).
SENSOR_WIND_SPEED: str = "wind_speed_3_avg"

#: SCADA column name for pitch angle (°).
SENSOR_PITCH_ANGLE: str = "sensor_5_avg"

#: SCADA column name for high-speed shaft gearbox bearing temperature (°C).
SENSOR_GEARBOX_BEARING: str = "sensor_11_avg"

#: SCADA column name for gearbox oil temperature (°C).
SENSOR_GEARBOX_OIL: str = "sensor_12_avg"

#: SCADA column name for generator drive-end (DE) bearing temperature (°C).
SENSOR_BEARING_DE: str = "sensor_13_avg"

#: SCADA column name for generator non-drive-end (NDE) bearing temperature (°C).
SENSOR_BEARING_NDE: str = "sensor_14_avg"

#: SCADA column name for generator stator winding temperature phase 1 (°C).
SENSOR_STATOR_PHASE1: str = "sensor_15_avg"

#: SCADA column name for generator stator winding temperature phase 2 (°C).
SENSOR_STATOR_PHASE2: str = "sensor_16_avg"

#: SCADA column name for generator stator winding temperature phase 3 (°C).
SENSOR_STATOR_PHASE3: str = "sensor_17_avg"

#: SCADA column name for generator rotational speed (rpm).
SENSOR_GENERATOR_RPM: str = "sensor_18_avg"

#: SCADA column name for grid active power output (kW).
SENSOR_GRID_POWER: str = "power_30_avg"

#: SCADA column name for high-voltage transformer temperature phase L1 (°C).
SENSOR_TRANSFORMER_L1: str = "sensor_38_avg"

#: SCADA column name for high-voltage transformer temperature phase L2 (°C).
SENSOR_TRANSFORMER_L2: str = "sensor_39_avg"

#: SCADA column name for high-voltage transformer temperature phase L3 (°C).
SENSOR_TRANSFORMER_L3: str = "sensor_40_avg"

#: SCADA column name for hydraulic group oil temperature (°C).
SENSOR_HYDRAULIC_OIL: str = "sensor_41_avg"

#: SCADA column name for nacelle internal temperature (°C).
SENSOR_NACELLE_TEMP: str = "sensor_43_avg"

#: SCADA column name for rotor rotational speed (rpm).
SENSOR_ROTOR_RPM: str = "sensor_52_avg"

#: Normal operational health status tag.
HEALTH_STATUS_NORMAL: str = "NORMAL"

#: Watch operational health status tag.
HEALTH_STATUS_WATCH: str = "WATCH"

#: Warning operational health status tag.
HEALTH_STATUS_WARNING: str = "WARNING"

#: Critical operational health status tag.
HEALTH_STATUS_CRITICAL: str = "CRITICAL"

#: Fault probability threshold triggering a WATCH alert.
DEFAULT_HEALTH_THRESHOLD_WATCH: float = 0.35

#: Fault probability threshold triggering a WARNING alert.
DEFAULT_HEALTH_THRESHOLD_WARNING: float = 0.60

#: Fault probability threshold triggering a CRITICAL alert.
DEFAULT_HEALTH_THRESHOLD_CRITICAL: float = 0.85

#: Default advance warning horizon in days.
DEFAULT_MAINTENANCE_HORIZON_DAYS: float = 5.0

#: Standard SCADA recording interval in minutes.
DEFAULT_SCADA_SAMPLE_MINUTES: int = 10

#: Simulation scenario identifier for normal turbine operation.
SCENARIO_NORMAL: str = "normal"

#: Simulation scenario identifier for generator bearing thermal runaway.
SCENARIO_BEARING_OVERHEATING: str = "bearing_overheating"

#: Simulation scenario identifier for high-speed gearbox wear and oil degradation.
SCENARIO_GEARBOX_WEAR: str = "gearbox_wear"

#: Simulation scenario identifier for hydraulic group pressure decay and overheating.
SCENARIO_HYDRAULIC_LEAK: str = "hydraulic_leak"

#: Simulation scenario identifier for transformer winding overheating.
SCENARIO_TRANSFORMER_OVERHEATING: str = "transformer_overheating"

#: List of monitored turbine failure subsystems.
FAULT_SUBSYSTEMS: list[str] = [
    "Generator Bearing",
    "Gearbox",
    "Hydraulic Group",
    "Transformer",
]

__all__ = [
    "DEFAULT_HEALTH_THRESHOLD_CRITICAL",
    "DEFAULT_HEALTH_THRESHOLD_WARNING",
    "DEFAULT_HEALTH_THRESHOLD_WATCH",
    "DEFAULT_MAINTENANCE_HORIZON_DAYS",
    "DEFAULT_SCADA_SAMPLE_MINUTES",
    "FAULT_SUBSYSTEMS",
    "HEALTH_STATUS_CRITICAL",
    "HEALTH_STATUS_NORMAL",
    "HEALTH_STATUS_WARNING",
    "HEALTH_STATUS_WATCH",
    "SCENARIO_BEARING_OVERHEATING",
    "SCENARIO_GEARBOX_WEAR",
    "SCENARIO_HYDRAULIC_LEAK",
    "SCENARIO_NORMAL",
    "SCENARIO_TRANSFORMER_OVERHEATING",
    "SENSOR_AMBIENT_TEMP",
    "SENSOR_BEARING_DE",
    "SENSOR_BEARING_NDE",
    "SENSOR_GEARBOX_BEARING",
    "SENSOR_GEARBOX_OIL",
    "SENSOR_GENERATOR_RPM",
    "SENSOR_GRID_POWER",
    "SENSOR_HYDRAULIC_OIL",
    "SENSOR_NACELLE_TEMP",
    "SENSOR_PITCH_ANGLE",
    "SENSOR_ROTOR_RPM",
    "SENSOR_STATOR_PHASE1",
    "SENSOR_STATOR_PHASE2",
    "SENSOR_STATOR_PHASE3",
    "SENSOR_TRANSFORMER_L1",
    "SENSOR_TRANSFORMER_L2",
    "SENSOR_TRANSFORMER_L3",
    "SENSOR_WIND_SPEED",
]
