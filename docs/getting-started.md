# Getting started

## From clone to a green run

Python 3.12 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
make install        # pip install -e ".[dev,docs]"
make hooks          # git pre-commit hook: black, isort, flake8
cp .env.example .env
make lint
make test
python -m smarthack
```

If `make lint` and `make test` pass on a fresh clone, the setup is right.

## The Makefile

One target per intent, the same locally and in CI. `make help` lists them.

| Target | What it does |
|---|---|
| `make format` | Rewrites files with black and isort. |
| `make lint` | Checks only, touches no file: black, isort, flake8, mypy, docstring coverage. |
| `make test` | The whole suite. |
| `make test-fast` | Unit tests only: the loop while editing. |
| `make cov` | The whole suite with the coverage floor (80%). |
| `make docs` / `make docs-serve` | Build the site strictly / preview it. |
| `make docker-build` | The production image. |

## Starting a new project from this template

The name `smarthack` appears in a handful of files. After renaming the folder
`smarthack/`, find the rest with:

```bash
git grep -l smarthack
```

Expect: `pyproject.toml`, `tox.ini`, `.docstr.yaml`, `Makefile`, `Dockerfile`,
`mkdocs.yml`, `.github/workflows/ci.yml`, `smarthack/constants.py`, and a few test
files. Then fill in the `TODO` lines (`pyproject.toml` description, `README.md`,
`docs/index.md`, `smarthack/__init__.py`) and reset `CHANGELOG.md`.

!!! note "Not in the template on purpose"
    There is no `deploy` target: what it deploys to is not known yet. Add it to the
    Makefile and the CI workflow when it is.
