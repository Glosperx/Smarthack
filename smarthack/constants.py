"""
# Constants

Project-wide scalars that are not read from the environment: names, fixed paths,
magic numbers given a name. Anything an operator should be able to change without
editing code belongs in `config.py` instead, and in `.env.example`.

Imports nothing from the package, so every layer may import from it.

The following can be imported from this module:
- `APP_NAME`
"""

#: The application's name, used as the root logger name and in startup messages.
APP_NAME = "smarthack"

__all__ = ["APP_NAME"]
