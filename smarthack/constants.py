"""
# Constants

Project-wide scalars that are not read from the environment: names, fixed paths,
magic numbers given a name. Anything an operator should be able to change without
editing code belongs in `config.py` instead, and in `.env.example`.

Imports nothing from the package, so every layer may import from it.

The following can be imported from this module:
- `APP_NAME`
- `CHANNEL_CALL_DAYS`
- `CHANNEL_CALL_PROBABILITY`
- `CHANNEL_EMAIL_PROBABILITY`
- `CONFLICT_WINDOW_DAYS`
- `DECISION_CONNECT_TIMEOUT_SECONDS`
- `DECISION_TIMEOUT_SECONDS`
- `DEFAULT_MAINTENANCE_INTERVAL_MINUTES`
- `DEFAULT_MAINTENANCE_OFFSET_MINUTES`
- `MAINTENANCE_INPUT_TABLE`
- `MAINTENANCE_TABLE`
- `NO_FAILURE_DAYS`
- `NO_SUBSYSTEM`
- `PARK_TABLE`
- `PARK_VIEW`
- `TURBINE_TABLE`
- `DEFAULT_WIND_FORECAST_INTERVAL_MINUTES`
- `DEFAULT_WIND_FORECAST_OFFSET_MINUTES`
- `WIND_FORECAST_DAYS`
- `WIND_FORECAST_REPLACE_RPC`
- `WIND_FORECAST_TABLE`
"""

#: The application's name, used as the root logger name and in startup messages.
APP_NAME = "smarthack"

#: Default execution interval in minutes for the maintenance worker loop.
DEFAULT_MAINTENANCE_INTERVAL_MINUTES = 60

#: Minute offset after slot boundary to align worker runs (e.g. 00:02).
DEFAULT_MAINTENANCE_OFFSET_MINUTES = 2

#: Supabase view exposing wind parks with extracted latitude and longitude.
PARK_VIEW = "park_map"

#: Supabase table containing wind parks.
PARK_TABLE = "park"

#: Supabase table containing wind turbine assets.
TURBINE_TABLE = "turbine"

#: Supabase table containing daily maintenance predictions and health status.
MAINTENANCE_TABLE = "turbine_mentenance"

#: Supabase table containing pre-computed feature inputs for predictive maintenance.
MAINTENANCE_INPUT_TABLE = "turbine_maintenance_input"

#: Placeholder value stored when no subsystem is diagnosed for healthy turbines.
NO_SUBSYSTEM = "none"

#: Default interval in minutes between wind forecast refreshes: twice a day.
DEFAULT_WIND_FORECAST_INTERVAL_MINUTES = 720

#: Minute offset after the slot boundary for wind forecast refreshes (e.g. 00:05 and 12:05).
DEFAULT_WIND_FORECAST_OFFSET_MINUTES = 5

#: Forecast horizon, in days, stored per park.
WIND_FORECAST_DAYS = 7

#: Two turbines of one park whose predicted failure days are at most this many days apart are
#: treated as failing in the same interval, which makes the agent compare their output.
CONFLICT_WINDOW_DAYS = 1

#: A lead time of this many days or more (or none at all) means ML1 predicts no failure inside the
#: 7-day horizon, so the turbine has no failure day and cannot make two failures overlap.
NO_FAILURE_DAYS = 8

#: An alert includes a phone call when the lead time is at most this many days.
CHANNEL_CALL_DAYS = 2.0

#: An alert includes a phone call when the fault probability is at least this.
CHANNEL_CALL_PROBABILITY = 0.70

#: A turbine that is not otherwise flagged still gets an email when its fault probability is at
#: least this.
CHANNEL_EMAIL_PROBABILITY = 0.30

#: Longest the agent waits for one answer of the local decision model, in seconds. A constant, not a
#: setting: past it the rule decides, so a longer wait only delays the sweep.
DECISION_TIMEOUT_SECONDS = 10.0

#: Part of `DECISION_TIMEOUT_SECONDS` spent opening the connection: a server that is not running
#: is noticed in this time rather than after the whole timeout.
DECISION_CONNECT_TIMEOUT_SECONDS = 2.0

#: Supabase table holding the hourly wind forecast per park, fully replaced on every refresh.
WIND_FORECAST_TABLE = "park_wind_forecast"

#: Supabase function that atomically replaces every row of `WIND_FORECAST_TABLE`.
WIND_FORECAST_REPLACE_RPC = "replace_park_wind_forecast"

__all__ = [
    "APP_NAME",
    "CHANNEL_CALL_DAYS",
    "CHANNEL_CALL_PROBABILITY",
    "CHANNEL_EMAIL_PROBABILITY",
    "CONFLICT_WINDOW_DAYS",
    "DECISION_CONNECT_TIMEOUT_SECONDS",
    "DECISION_TIMEOUT_SECONDS",
    "DEFAULT_MAINTENANCE_INTERVAL_MINUTES",
    "DEFAULT_MAINTENANCE_OFFSET_MINUTES",
    "MAINTENANCE_INPUT_TABLE",
    "MAINTENANCE_TABLE",
    "NO_FAILURE_DAYS",
    "NO_SUBSYSTEM",
    "PARK_TABLE",
    "PARK_VIEW",
    "TURBINE_TABLE",
    "DEFAULT_WIND_FORECAST_INTERVAL_MINUTES",
    "DEFAULT_WIND_FORECAST_OFFSET_MINUTES",
    "WIND_FORECAST_DAYS",
    "WIND_FORECAST_REPLACE_RPC",
    "WIND_FORECAST_TABLE",
]
