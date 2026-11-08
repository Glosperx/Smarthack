# Smarthack

TODO: what this application does, in one or two sentences.

<iframe src="https://mermaid.live/embed?theme=default&look=classic&mode=light#pako:eNqNVcGO00gQ_ZVWn0CbEZrsYaVoBTLEsNl1ZqLEcABzKNudpEXHbbXbjDTDnPgKxI0P4CfgwGfxqm2HwZFYojm0q7peVb161XMjC1sqOZNbY6-KPTkvknXmskrg17T5zlG9F_MojV9lck5eZfL14Obf5kk0j-BKlVEH5Z1Wnenv3D14SMK3LteVMtaN4pZxGl8ibuXsrrLXX98LRCsbwi5rVZ0t-fNOkKpKPp6UlkT_9aWRMPRGiXubP8UfIqFDXpJo9KE15O-Psj-NoxRBGxRdeHJKbBWhVHXWOh1KQAXeteIAbsxvFLFMgLbkywrncavJOXuT85monSp18e0jWCrVFrlVl83ZnHJttAfB4tsHLa41kOovnyoQY6i_fII7DbhTxrVl2-GqxusD-a_v-z5cPwMA1Ur8FZB_o6PoWXzBFEU7MAE2q90ztk8EI9bkilExq_WCxznvuhKEimrN3Xz5XAlUVD_qO9XWaa-vmfSyrbmqY-1jyCS6YIUYqvRWFxzhFFIT7nZTskIVew2QSUdY0Yq34MyLxlA-Qvs3fnHTz0gYW5ABqfgr9LXuh4A8gfuCqs5LRjkQmcnb_2UrideBLY5AoaPc8TJasELiA2kz8kWrmF1Rjbo89LO1lS5Emm5CUYtqa3NdiwcivYI-frEQYevE2dnDIO5wgOQGb1i33jg9NTLVR2ty3tkw0R-26YmNz8fgcADFgxNHNr3LJL0FJWHemXzXMXF6qWBNFHyB6fiV_yeA8BFSx0_-YX5ZDbwtYkeu5Mkd2WLc4eZd2oZu549f3cOD0NaUUzNsZb-sYR0xFXRw_wg4fxziotUqTM9AoGH_rlQeop9S46PVAk8RP6rQ-VrRcYVPBHRx-Xwkdd4xvEaisnqkmHW84bvWqwoZIVVljYZ2sd5TAYCQPuzBBAtjtNoCIBS7WaQhdqM9Q0PopS5P3_R0HV3wtXWL_e1fQu-oamrrfPew70BTP5OxIIMYOdHAz2AMsHeNciJ3TpdyhgRqIg_KYT_wKbGofo9_J5mcZRJvH7UGzE0yaax9E4yFoabh7LcAqal6ae1hwHG23e3lbEumwVdbc4dzTSC6v3L7HQCPPlo" width="100%" height="480" style="border:0" loading="lazy" title="Mermaid diagram" sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"></iframe>

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
