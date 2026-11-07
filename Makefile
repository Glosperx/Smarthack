PACKAGE := smarthack
IMAGE   ?= smarthack
VENV    ?= .venv
BIN     := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin,)
PYTHON  := $(if $(BIN),$(BIN)/python,python3)
PIP     := $(if $(BIN),$(BIN)/pip,pip3)
UVICORN := $(if $(BIN),$(BIN)/uvicorn,uvicorn)
PYTEST  := $(if $(BIN),$(BIN)/pytest,pytest)

.DEFAULT_GOAL := help
.PHONY: help install hooks format lint test test-fast cov docs docs-serve docker-build clean dev dev-api dev-web types build serve check test-db

help:                       # list the targets
	@grep -E '^[a-z-]+:.*# ' $(MAKEFILE_LIST) | sed -E 's/:[^#]*# /\t/'

test-db:                   # test connectivity to Supabase using .env credentials
	$(PYTHON) -c 'import asyncio, httpx, json; from smarthack.clients.supabase_parks import fetch_parks; print(json.dumps(asyncio.run(fetch_parks(httpx.AsyncClient())), indent=2))'

install:                    # editable install with backend dev extras and frontend npm dependencies
	@if [ ! -d "$(VENV)" ]; then python3 -m venv $(VENV); fi
	$(VENV)/bin/pip install -e ".[dev,docs]"
	if [ -f frontend/package.json ]; then cd frontend && npm install; fi

dev:                       # run both backend and frontend dev servers concurrently
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
