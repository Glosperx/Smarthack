# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Real phone calls from the dispatch agent (`docs/lake.md`): with `VOICE_CALLS_ENABLED=true` a
  CRITICAL alert is handed to the alerting module (`experiments/alerting`), which emails and
  phones on-call with its allowlist, `DRY_RUN` and once-per-alert gates. Off by default. New
  `calls` extra (`twilio`, `jinja2`, `requests`).
- Maintenance pipeline on the local data lake (`docs/lake.md`): three chained Lambda-shaped
  handlers. `raw` keeps only the features the maintenance model reads (selected, or derived
  from raw SCADA sensors, following the model's `fault_features.json`) and writes them to
  `features`; `features` scores every turbine with the model into `predictions`; `predictions`
  runs the LangGraph dispatch agent for every park with a turbine to repair and writes its
  plan to `dispatch`. `make lake-sample` puts simulated SCADA into `raw` to run it end to end.
- Local data lake (`docs/lake.md`): S3 buckets simulated as folders under `LAKE_DIR`
  (`data/lake/`), with atomic uploads (`make lake-put`) and a watcher (`make lake-watch`, also
  started by `make up`) that hands each new CSV file in `raw/` to a Lambda-shaped handler.
  The handler logs the file and its first rows; unreadable files go to `failed/`. New `lake`
  extra (`watchdog`) and `LAKE_DIR`.
- Oversize transport network (`docs/transport.md`): every major road of Romania coloured for a
  2.4-3 MW turbine convoy (60 m, 4.8 m high, 4.5 m wide, 120 t) from OpenStreetMap limits and
  curve geometry, with reachability from the ports of Constanța, Galați and Brăila.
  `make transport` builds `models/transport/`; served by `/api/transport/*` and shown by the
  **Oversize transport** panel on the map.
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
