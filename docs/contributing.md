# Contributing

## Branches

| Branch | Role |
|---|---|
| `main` | Closed. Only receives releases, merged from `dev` through a pull request. |
| `dev` | Integration branch, protected: nothing is pushed to it directly. A change reaches it through a pull request with one approval and green CI. |
| `feature/<short-name>`, `fix/<short-name>` | Where the work happens. Branched from `dev`, merged back into `dev`. |

## Workflow

1. Branch from `dev`.
2. `make format`, then edit; `make test-fast` while you work.
3. `make lint` and `make test` before you push: they are the commands CI runs.
4. Open a pull request **into `dev`**. The template carries the definition of done below.
5. CI must be green (`lint`, `test`, `docs`, `docker`) and the pull request approved by
   someone other than its author before it merges.

The pre-commit hook (`make hooks`) runs black, isort and flake8 on every commit. mypy is
deliberately not in it: it needs every library's types, which would duplicate the
environment. It runs in `make lint` and in CI.

## Definition of done

- [ ] New code sits in the right layer, and every import points down.
- [ ] Module docstring with the "can be imported" list; class docstring; `:param:` and
      `:returns:` on every public function.
- [ ] Any new dependency is in the correct extra (or core), pinned to an exact version.
- [ ] Any new environment variable is read in `config.py` and listed in `.env.example`.
- [ ] At least one test under `tests/unit/`; `make test` passes.
- [ ] `make lint` passes, docstring gate included.
- [ ] `CHANGELOG.md` and the affected pages in `docs/` are updated.
- [ ] Validated on a real run, not just unit tests.

## Dependencies

Every dependency is pinned with `==`, so CI checks with the versions the code was checked
with locally. Core goes in `dependencies`; anything one domain needs goes in its own extra.
black, isort and flake8 are pinned twice, in `pyproject.toml` and in
`.pre-commit-config.yaml`; a test fails when the two differ, so bump both together.

## Artifacts do not go in Git

Models, datasets, caches and build output stay out of the repository (`.gitignore` is broad
on purpose). An artifact committed to Git is one nobody is really versioning.
