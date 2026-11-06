# Serving

## The image

The `Dockerfile` has three stages:

| Stage | Purpose |
|---|---|
| `build` | Installs the package and its dependencies into a virtualenv. Dependencies come first, so editing code does not reinstall them. |
| `production` | The smallest image that runs the application, as a non-root user. Runs `python -m smarthack`. |
| `serving` | `production` plus what a long-running service needs (`PORT`, `EXPOSE`). |

```bash
make docker-build                                       # production
docker build --target serving -t smarthack-serving .
docker run --rm --env-file .env smarthack
```

`.env` is never copied into an image. Configuration arrives at run time, through
`--env-file` or the platform's secret store.

!!! note "Not implemented yet"
    The `serving` stage runs the same command as `production`: the application has not
    chosen a server. When it does, replace its `CMD`, and add the server's package to a
    `serving` extra in `pyproject.toml` (and to `EXTRA_MODULES` in `tests/conftest.py`).

!!! note "Not implemented yet"
    There is no `deploy` target in the Makefile or the CI workflow, because where this
    deploys to is not decided. CI builds both stages and smoke-tests `production`, so the
    image is known to build and start.
