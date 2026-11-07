"""
# Constants

Project-wide scalars that are not read from the environment: names, fixed paths,
magic numbers given a name. Anything an operator should be able to change without
editing code belongs in `config.py` instead, and in `.env.example`.

Imports nothing from the package, so every layer may import from it.

The following can be imported from this module:
- `APP_NAME`
- `MAINTENANCE_TABLE`
- `PARK_TABLE`
- `PARK_VIEW`
- `TURBINE_TABLE`
"""

#: The application's name, used as the root logger name and in startup messages.
APP_NAME = "smarthack"

#: Supabase view exposing wind parks with extracted latitude and longitude.
PARK_VIEW = "park_map"

#: Supabase table containing wind parks.
PARK_TABLE = "park"

#: Supabase table containing wind turbine assets.
TURBINE_TABLE = "turbine"

#: Supabase table containing daily maintenance predictions and health status.
MAINTENANCE_TABLE = "turbine_mentenance"

__all__ = ["APP_NAME", "MAINTENANCE_TABLE", "PARK_TABLE", "PARK_VIEW", "TURBINE_TABLE"]
