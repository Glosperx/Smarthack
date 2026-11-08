# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Decision model in the dispatch agent (`docs/decision_model.md`): a local Jeffan 4B server
  (`make decision-server`, `experiments/decision_model`) and `smarthack/clients/decision_client.py`.
  The new `choose_repair_plan` node lets the model pick among the optimum and alternative repair
  plans, refused when its pick saves fewer turbines; the alert channel can be scored per turbine.
  `DECISION_MODEL_ENABLED` (off by default), `DECISION_MODEL_URL` and `DECISION_MODEL_MODE`
  (`umbra`, the default, only logs the model's choice; `activ` lets it decide). Any model error
  falls back to the rule. On the test data the model ties the rules.
- Langfuse tracing of the dispatch agent (`docs/tracing.md`): one trace per run with every graph
  node and every question to the decision model, crew phones and emails masked before sending.
  New `monitoring` extra (`langfuse`, `langchain`), `LANGFUSE_ENABLED` (off by default),
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL`.
  Crew names, phones and emails are masked before sending, including the ones the agent loaded
  for the park, whatever their format; an SDK that is installed but broken switches tracing off
  instead of stopping the sweep. `langfuse` and `opentelemetry` are mypy-optional like the other
  extras.
- Hill wind site finder (`docs/wind_resource.md`): forecast mean wind at 100 m for the next two
  full years on Romania's 200-800 m hills, from NASA POWER (backtested method choice and P10-P90
  band), Global Wind Atlas terrain detail and Copernicus DEM. `make resource` builds
  `models/resource/`; `/api/resource/{summary,sites,heatmap.png,point}` serve it; the map has a
  Site finder panel with the heatmap, 15 ranked candidate sites and click-to-query. New
  `resource` extra, `RESOURCE_CACHE_DIR` and `RESOURCE_ATLAS_DIR`.
- `park_wind_forecast` table (Flyway `V18`) holding the hourly 7-day wind forecast per park, and
  the `wind_forecast_job` worker (`make forecast`, `make forecast-worker`) that replaces it
  atomically from Open-Meteo twice a day.
- The foundation layer: `config` (the only reader of the environment), `constants`,
  `utils/logging_utils` and `utils/optional_imports`, and the `python -m smarthack` entry point.
- Tooling: black, isort, flake8, mypy and docstr-coverage behind `make lint`, the same hooks
  in pre-commit (mypy aside), and GitHub Actions jobs for lint, tests, docs and Docker.
- Guards in `tests/unit/`: layering (imports point down), module docstrings (export list matches
  `__all__`), and repository files (`.env.example` matches `config.py`, tool pins match pre-commit).
- Multi-stage `Dockerfile` (build, production, serving), `mkdocs` site under `docs/`.

### Changed

- `rank_and_match_crews` now runs after the repair plan and orders turbines by their repair day
  (turbines that cannot be saved last); the old "CRITICAL first" sort is gone. `schedule_repairs`
  reads the failing turbines, not the ranked ones.
- A call alert (`AlertChannel.VOICE_CALL`) now sends the call and the email. The channel values
  are `email_si_apel`, `doar_email` and `nimic` (member names unchanged), which changes the
  `alert_channel` values the API returns.
- A lead time of 8 days or more, or none, is no failure day: such a turbine no longer makes two
  failures overlap. A missing or `None` lead time no longer crashes the alert node.
- The channel rule thresholds (2 days, 0.70, 0.30) are constants in `constants.py`.

### Fixed

- `predict_wind_power_mwh` returned 0.0 MWh on every real run: it read a key the wind predictor
  never sets. It now returns the horizon's total from the predictor's `summary`, so the power
  model's comparison of competing turbines, and the repair schedule weights, use real output.
