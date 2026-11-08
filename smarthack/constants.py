"""
# Constants

Project-wide scalars that are not read from the environment: names, fixed paths,
magic numbers given a name. Anything an operator should be able to change without
editing code belongs in `config.py` instead, and in `.env.example`.

Imports nothing from the package, so every layer may import from it.

The following can be imported from this module:
- `APP_NAME`
- `CONFLICT_WINDOW_DAYS`
- `DEFAULT_MAINTENANCE_INTERVAL_MINUTES`
- `DEFAULT_MAINTENANCE_OFFSET_MINUTES`
- `LAKE_DISPATCH_BUCKET`
- `LAKE_FAILED_BUCKET`
- `LAKE_FEATURES_BUCKET`
- `LAKE_OBJECT_SUFFIXES`
- `LAKE_PREDICTIONS_BUCKET`
- `LAKE_PREVIEW_ROWS`
- `LAKE_RAW_BUCKET`
- `LAKE_TEMP_SUFFIX`
- `MAINTENANCE_INPUT_TABLE`
- `MAINTENANCE_TABLE`
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

#: Supabase table holding the hourly wind forecast per park, fully replaced on every refresh.
WIND_FORECAST_TABLE = "park_wind_forecast"

#: Supabase function that atomically replaces every row of `WIND_FORECAST_TABLE`.
WIND_FORECAST_REPLACE_RPC = "replace_park_wind_forecast"

#: The landing bucket of the local data lake: new telemetry files arrive here.
LAKE_RAW_BUCKET = "raw"

#: The bucket a file that could not be processed is copied to, under the same key.
LAKE_FAILED_BUCKET = "failed"

#: The model's input: one row per turbine, only the features the maintenance model reads.
LAKE_FEATURES_BUCKET = "features"

#: The maintenance model's assessment of every turbine of a features file, as JSON.
LAKE_PREDICTIONS_BUCKET = "predictions"

#: What the dispatch agent decided for the parks of a predictions file, as JSON.
LAKE_DISPATCH_BUCKET = "dispatch"

#: The file types the lake handlers process; anything else is ignored. Each handler reads one.
LAKE_OBJECT_SUFFIXES = (".csv", ".json")

#: Suffix of an object still being written. Ignored until it is renamed to its final key.
LAKE_TEMP_SUFFIX = ".tmp"

#: How many rows of a newly arrived file are written to the log.
LAKE_PREVIEW_ROWS = 5

__all__ = [
    "APP_NAME",
    "CONFLICT_WINDOW_DAYS",
    "DEFAULT_MAINTENANCE_INTERVAL_MINUTES",
    "DEFAULT_MAINTENANCE_OFFSET_MINUTES",
    "LAKE_DISPATCH_BUCKET",
    "LAKE_FAILED_BUCKET",
    "LAKE_FEATURES_BUCKET",
    "LAKE_OBJECT_SUFFIXES",
    "LAKE_PREDICTIONS_BUCKET",
    "LAKE_PREVIEW_ROWS",
    "LAKE_RAW_BUCKET",
    "LAKE_TEMP_SUFFIX",
    "MAINTENANCE_INPUT_TABLE",
    "MAINTENANCE_TABLE",
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
