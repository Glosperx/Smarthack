PACKAGE := smarthack
IMAGE   ?= smarthack
VENV    ?= $(if $(wildcard /home/stefan/sandbox/.venv/bin/python),/home/stefan/sandbox/.venv,.venv)
BIN     := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin,)
PYTHON  := $(if $(BIN),$(BIN)/python,python3)
PIP     := $(if $(BIN),$(BIN)/pip,pip3)
UVICORN := $(if $(BIN),$(BIN)/uvicorn,uvicorn)
PYTEST  := $(if $(BIN),$(BIN)/pytest,pytest)

.DEFAULT_GOAL := help
.PHONY: help install hooks format lint test test-fast cov docs docs-serve docker-build clean dev dev-servers dev-api dev-web types build serve check test-db predict worker forecast forecast-worker lake-watch lake-put lake-sample resource transport up

help:                       # list the targets
	@grep -E '^[a-z-]+:.*# ' $(MAKEFILE_LIST) | sed -E 's/:[^#]*# /\t/'

test-db:                   # test connectivity to Supabase using .env credentials
	$(PYTHON) -c 'import asyncio, httpx, json; from smarthack.clients.supabase import fetch_parks; print(json.dumps(asyncio.run(fetch_parks(httpx.AsyncClient())), indent=2))'

predict:                   # run one maintenance prediction cycle now
	$(PYTHON) -m smarthack.jobs.maintenance_job $(ARGS)

worker:                    # run continuous scheduled prediction loop
	$(PYTHON) -m smarthack.jobs.maintenance_job --every 10 $(ARGS)

forecast:                  # refresh the 7-day park wind forecast once now
	$(PYTHON) -m smarthack.jobs.wind_forecast_job $(ARGS)

forecast-worker:           # keep refreshing the park wind forecast twice a day
	$(PYTHON) -m smarthack.jobs.wind_forecast_job --every $(ARGS)

lake-watch:                # run the lake handlers on every new file in data/lake/; ARGS=--polling in Docker
	$(PYTHON) -m smarthack.jobs.lake_job watch $(ARGS)

lake-put:                  # upload FILE=path/to/file.csv into the raw bucket atomically
	$(PYTHON) -m smarthack.jobs.lake_job put "$(FILE)" $(ARGS)

lake-sample:               # put simulated SCADA telemetry into raw: runs raw -> features -> predictions -> dispatch
	$(PYTHON) -m smarthack.jobs.lake_job sample $(ARGS)

test-agent:                # run autonomous LangGraph agent dispatch test with live logs
	$(PYTHON) scripts/test_agent.py $(ARGS)

resource:                  # build the hill wind atlas (heatmap, sites, backtest); add ARGS=--no-names offline
	$(PYTHON) scripts/build_wind_resource.py $(ARGS)

up:                        # ONE command: setup checks, migrations, then API + web + all background jobs
	$(PYTHON) scripts/run_all.py $(ARGS)

transport:                 # build the oversize transport road network (first run downloads ~330 MB of OSM)
	$(PYTHON) scripts/build_transport.py $(ARGS)

install:                    # editable install with backend dev extras and frontend npm dependencies
	@if [ ! -d "$(VENV)" ]; then python3 -m venv $(VENV); fi
	$(VENV)/bin/pip install -e ".[dev,docs]"
	if [ -f frontend/package.json ]; then cd frontend && npm install; fi

dev:                       # run backend API, frontend web, and maintenance worker concurrently
	$(MAKE) -j3 dev-api dev-web worker

dev-servers:               # run backend API and frontend web only (without background worker)
	$(MAKE) -j2 dev-api dev-web

dev-api:                   # run FastAPI dev server with auto-reload on :8000
	$(UVICORN) smarthack.api.app:create_app --factory --reload --port 8000

dev-web:                   # run Vite frontend dev server on :5173
	cd frontend && npm run dev

types:                     # export OpenAPI schema from FastAPI and generate TypeScript types
	$(PYTHON) -c "import json; from smarthack.api.app import create_app; print(json.dumps(create_app().openapi()))" > frontend/openapi.json
	cd frontend && npx openapi-typescript openapi.json -o src/types/api.ts

build:                     # build React application for production
	cd frontend && npm run build

serve: build               # run single-process demo serving API and static frontend assets
	$(PYTHON) -m smarthack

check:                     # run linting, pytest, and frontend typecheck
	$(PYTEST) -rs --ignore=tests/unit/wind && cd frontend && npx tsc --noEmit

hooks:                      # install the git pre-commit hook
	$(if $(BIN),$(BIN)/pre-commit,pre-commit) install

format:                     # writes
	$(if $(BIN),$(BIN)/black,black) $(PACKAGE) tests
	$(if $(BIN),$(BIN)/isort,isort) $(PACKAGE) tests

lint:                       # checks only - touches no file; the same command CI runs
	$(if $(BIN),$(BIN)/black,black) --check $(PACKAGE) tests
	$(if $(BIN),$(BIN)/isort,isort) --check-only $(PACKAGE) tests
	$(if $(BIN),$(BIN)/flake8,flake8) $(PACKAGE) tests
	$(if $(BIN),$(BIN)/mypy,mypy)
	$(if $(BIN),$(BIN)/docstr-coverage,docstr-coverage) $(PACKAGE)

test:                       # the whole suite
	$(PYTEST) -rs

test-fast:                  # unit tests only, the loop to run while editing
	$(PYTEST) -rs -m "not integration"

cov:                        # whole suite with the coverage floor CI enforces
	$(PYTEST) -rs --cov --cov-report=term-missing --cov-fail-under=80

docs:                       # build the site into ./site, failing on any broken link
	$(if $(BIN),$(BIN)/mkdocs,mkdocs) build --strict

docs-serve:                 # live preview at http://127.0.0.1:8000
	$(if $(BIN),$(BIN)/mkdocs,mkdocs) serve

docker-build:               # the production image; add --target serving for the other
	docker build --target production -t $(IMAGE):latest .

clean:                      # remove build and cache artifacts
	rm -rf build dist site .coverage htmlcov .pytest_cache .mypy_cache *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
