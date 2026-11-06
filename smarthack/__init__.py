"""
# Smarthack

TODO: what this application is, in two lines. The rule that holds the code
together: dependencies flow strictly downward, and `tests/unit/test_layering.py`
fails the build when an import points up.

- `config`: the single reader of the environment
- `constants`: project-wide scalars
- `utils`: cross-cutting helpers shared by every layer

```bash
python -m smarthack   # starts the application
```

The following can be imported from this module:
- `__version__`
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
