# Testing

## Layout

```
tests/
├── conftest.py        # isolation fixture, helpers for optional extras
├── unit/              # sub-second, synthetic data, no network, no process
└── integration/       # starts a process, chains steps, talks to a service
```

A test is *unit* if it runs sub-second and touches nothing outside the process;
*integration* if it starts a process, chains steps or talks to a service. Integration
tests carry `pytest.mark.integration`, so `make test-fast` skips them. A unit test that
turns out slow is marked the same way rather than slowing the loop.

## The guards

Three files check the repository rather than a feature. They are the most valuable tests
here; do not delete one because it is in the way.

| File | What fails the build |
|---|---|
| `test_layering.py` | An import that points to a higher layer, or a folder with no rank. |
| `test_module_docstrings.py` | A module whose docstring export list differs from `__all__`. |
| `test_repository_files.py` | A variable in `.env.example` that `config.py` does not read (or the reverse), a config accessor nothing calls, black/isort/flake8 pinned differently in `pyproject.toml` and pre-commit, an extra the tests do not know. |

## Optional extras

The suite runs on two installs: everything, and the core alone. A test that needs an extra
says so, and skips on the core install, naming the extra, instead of failing:

```python
from tests.conftest import requires_extra, skip_module_without_extra

skip_module_without_extra("aws")      # top of a file, BEFORE importing the module under test

@requires_extra("aws")                # one test
def test_reads_from_s3() -> None: ...
```

Each extra's import names are written once, in `EXTRA_MODULES` in `tests/conftest.py`.

## What to test

The contract, not the arithmetic: that a class instantiates with its documented parameters,
that a function returns the documented shape, that a missing setting falls back to its
default and a bad one fails loudly. Seed anything random; a failure must be reproducible.

!!! note "Known incompleteness"
    There are no fixtures for domain data yet. When the application has some, put the shared
    ones in `tests/conftest.py` with their assertion helpers, so a shape change is one edit.
