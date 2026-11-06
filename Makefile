PACKAGE := smarthack
IMAGE   ?= smarthack

.DEFAULT_GOAL := help
.PHONY: help install hooks format lint test test-fast cov docs docs-serve docker-build clean

help:                       # list the targets
	@grep -E '^[a-z-]+:.*# ' $(MAKEFILE_LIST) | sed -E 's/:[^#]*# /\t/'

install:                    # editable install with the dev and docs extras
	pip install -e ".[dev,docs]"

hooks:                      # install the git pre-commit hook
	pre-commit install

format:                     # writes
	black $(PACKAGE) tests
	isort $(PACKAGE) tests

lint:                       # checks only - touches no file; the same command CI runs
	black --check $(PACKAGE) tests
	isort --check-only $(PACKAGE) tests
	flake8 $(PACKAGE) tests
	mypy
	docstr-coverage $(PACKAGE)

test:                       # the whole suite
	pytest -rs

test-fast:                  # unit tests only, the loop to run while editing
	pytest -rs -m "not integration"

cov:                        # whole suite with the coverage floor CI enforces
	pytest -rs --cov --cov-report=term-missing --cov-fail-under=80

docs:                       # build the site into ./site, failing on any broken link
	mkdocs build --strict

docs-serve:                 # live preview at http://127.0.0.1:8000
	mkdocs serve

docker-build:               # the production image; add --target serving for the other
	docker build --target production -t $(IMAGE):latest .

clean:                      # remove build and cache artifacts
	rm -rf build dist site .coverage htmlcov .pytest_cache .mypy_cache *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
