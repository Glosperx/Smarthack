# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- The foundation layer: `config` (the only reader of the environment), `constants`,
  `utils/logging_utils` and `utils/optional_imports`, and the `python -m smarthack` entry point.
- Tooling: black, isort, flake8, mypy and docstr-coverage behind `make lint`, the same hooks
  in pre-commit (mypy aside), and GitHub Actions jobs for lint, tests, docs and Docker.
- Guards in `tests/unit/`: layering (imports point down), module docstrings (export list matches
  `__all__`), and repository files (`.env.example` matches `config.py`, tool pins match pre-commit).
- Multi-stage `Dockerfile` (build, production, serving), `mkdocs` site under `docs/`.
