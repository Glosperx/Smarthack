# Smarthack

TODO: what this application does, in one or two sentences.

## Quick start

Python 3.12 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
make install          # editable install with the dev and docs extras
make hooks            # git pre-commit hook
cp .env.example .env
make lint && make test
python -m smarthack
```

## Layout

```
smarthack/        the package: config, constants, utils, entry point
tests/unit/       fast tests, plus the guards that check the repository itself
tests/integration/
docs/             mkdocs site (make docs-serve)
```

`make help` lists every target. The architecture, the testing approach and the definition
of done are in [`docs/`](docs/index.md).

## Tooling

| What | Where |
|---|---|
| Dependencies, core and extras, exact pins | `pyproject.toml` |
| black, isort, flake8, mypy, docstring coverage | `make lint` |
| Git hook (black, isort, flake8) | `.pre-commit-config.yaml` |
| Environment variables, every one | `.env.example`, read only in `smarthack/config.py` |
| Image: build, production, serving | `Dockerfile` |
| CI: lint, test, docs, docker | `.github/workflows/ci.yml` |
