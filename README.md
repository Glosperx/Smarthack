# Smarthack

TODO: what this application does, in one or two sentences.

```mermaid
flowchart LR
    subgraph DATE["Date"]
        SCADA["Telemetrie SCADA<br/>a turbinelor"]
        METEO["Prognoză meteo<br/>Open-Meteo"]
    end

    subgraph LAKE["Data lake (S3 + Lambda simulat)"]
        FEAT["Selectare feature-uri<br/>pentru model"]
    end

    subgraph ML["Modele ML"]
        ML1["ML1: predicție defecte<br/>probabilitate și zile până la defect"]
        ML2["ML2: producție estimată<br/>per turbină pe 7 zile"]
    end

    subgraph AGENT["Agent LangGraph, per parc"]
        PRIO["Defecte apropiate în timp?<br/>prioritizare după producție"]
        PLAN["Planificare reparații<br/>o echipă, zile cu vânt slab"]
        JEV{"Model local de decizie<br/>plan și canal de alertă"}
    end

    subgraph ALERT["Alertare"]
        EMAIL["Email"]
        APEL["Apel telefonic TTS<br/>Infobip / Twilio"]
    end

    SCADA --> FEAT --> ML1
    METEO --> ML2
    METEO --> PLAN
    ML1 --> PRIO
    ML2 --> PRIO
    PRIO --> PLAN --> JEV
    JEV -->|"avertizare"| EMAIL
    JEV -->|"critic"| APEL
    JEV -->|"critic"| EMAIL
    EMAIL --> ECH["Echipa de gardă"]
    APEL --> ECH

    ML1 --> DB[("Supabase<br/>predicții zilnice")]
    DB --> APP["Aplicație web<br/>FastAPI + hartă React"]

    subgraph NOU["Planificare parcuri noi"]
        RES["Potențial eolian pe 2 ani<br/>vânt, relief"] --> SITES["Situri candidate"]
        TRANS["Rute pentru transport<br/>agabaritic"]
    end
    SITES --> APP
    TRANS --> APP
```

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

## Run everything

```bash
make up                       # or: python scripts/run_all.py
```

Checks `.env` and dependencies, applies Flyway migrations, then starts the API (:8000), the
frontend (:5173), the maintenance worker and the wind forecast worker. Ctrl+C stops all.
Options: `--skip-migrate`, `--no-web`, `--no-workers`, `--prod`, `--port N`.

## Layout

```
smarthack/        the package: config, constants, utils, entry point
tests/unit/       fast tests, plus the guards that check the repository itself
tests/integration/
docs/             mkdocs site (make docs-serve)
```

`make help` lists every target. The architecture, the testing approach and the definition
of done are in [`docs/`](docs/index.md).

## Branches

| Branch | Role |
|---|---|
| `main` | Closed. Only receives releases, merged from `dev` through a pull request. |
| `dev` | **Protected.** Nothing is pushed to it directly: a change merges only through a pull request with **one approval** and green CI (`lint`, `test`, `docs`, `docker`). |
| `feature/<name>`, `fix/<name>` | Where the work happens: branch from `dev`, open the pull request into `dev`. |

The full workflow and the definition of done are in [`docs/contributing.md`](docs/contributing.md).

## Tooling

| What | Where |
|---|---|
| Dependencies, core and extras, exact pins | `pyproject.toml` |
| black, isort, flake8, mypy, docstring coverage | `make lint` |
| Git hook (black, isort, flake8) | `.pre-commit-config.yaml` |
| Environment variables, every one | `.env.example`, read only in `smarthack/config.py` |
| Image: build, production, serving | `Dockerfile` |
| CI: lint, test, docs, docker | `.github/workflows/ci.yml` |
