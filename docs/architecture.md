# Architecture

## One direction of dependency

Code is arranged in layers, and a layer may import from its own rank or below, never
above. Today there is one: the foundation.

```
smarthack/
├── __init__.py          # __version__ only
├── __main__.py          # entry point: imports what it starts, imported by nothing
├── config.py            # the ONLY reader of os.environ
├── constants.py         # project-wide scalars
└── utils/
    ├── logging_utils.py     # the ONLY place that configures logging
    └── optional_imports.py  # missing extra vs real bug
```

`tests/unit/test_layering.py` parses every file with `ast` and fails the build when an
import points up, including imports inside functions and under `TYPE_CHECKING`. A new
top-level folder fails it too until it is given a rank in `RANKS`: a layer cannot arrive
unchecked.

!!! tip "Where new code goes"
    A new concern gets its own folder at the rank of the highest layer it imports from,
    with an abstract contract at its root. Add it to `RANKS`, add it to the layout above,
    and put its tests under `tests/unit/<folder>/`, mirroring the code.

## Rules that hold it together

1. **One reader of the environment.** Only `config.py` touches `os.environ`. Every other
   module imports an accessor. Values are read on each call, never at import time.
2. **One configurer of logging.** Modules call `logging.getLogger(__name__)` and configure
   nothing, so importing the package never overrides an embedding application's logging.
3. **Importing never needs credentials.** A cloud client is built in `config.py` inside a
   `try/except` that leaves `None` on failure; the caller that needs it turns `None` into a
   loud error.
4. **Optional dependencies live in extras**, pinned exactly, with a guarded import that
   tells a missing extra from a typo (`utils/optional_imports.py`). Heavy libraries are
   imported inside the function that uses them, with a comment saying why.
5. **Either complete or absent.** Nothing is registered, exported or documented as an option
   until it works. A TODO in the docs is free; an option that crashes costs trust.

## Docstrings: the format

Every module ends its docstring with the list of what it exports, and `__all__` says the
same thing. `tests/unit/test_module_docstrings.py` fails when the two differ.

```python
"""
# Module title

What it is for, and the decision a reader would otherwise have to rediscover.

The following can be imported from this module:
- `function_name`
- `CONSTANT_NAME`
"""
```

Every public function documents its parameters and result, with a Sphinx field list:

```python
def configure_logging(level: str | None = None, force: bool = False) -> None:
    """
    Configure the root logger once.

    :param level: Logging level name. Defaults to None, meaning the environment's.
    :param force: Whether to reconfigure even if this already ran.

    :returns: None.
    :raises ValueError: When `level` is not a logging level.
    """
```

`docstr-coverage` (floor 95%, in `.docstr.yaml`) checks that a docstring exists; the test
above checks the one part of it no tool reads.
