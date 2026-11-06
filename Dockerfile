# Multi-stage: build -> production -> serving. The same image locally, in CI and in the cloud.
#
#   docker build --target production -t smarthack .   # what `make docker-build` runs
#   docker build --target serving    -t smarthack-serving .
#   docker run --rm --env-file .env smarthack
#
# `.env` is never copied into an image (.dockerignore): pass configuration at run
# time with --env-file or the platform's own secret store.

# --- build: compile the package and its dependencies into a virtualenv -------------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src

# Dependencies first, from pyproject.toml alone, so editing code does not reinstall
# them: this layer is cached until the dependency list changes.
COPY pyproject.toml README.md ./
COPY smarthack/__init__.py smarthack/__init__.py
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

# The code last. A plain install, not editable: the image holds the package, not a link to /src.
COPY smarthack smarthack
RUN /opt/venv/bin/pip install --no-deps --force-reinstall .

# --- production: the smallest image that runs the application ----------------------
FROM python:3.12-slim AS production

# Where the image came from: GitHub's package page links back to the repository.
LABEL org.opencontainers.image.title="smarthack" \
      org.opencontainers.image.source="https://github.com/Glosperx/Smarthack"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

# Not root: a compromised process should not own the container.
RUN useradd --system --create-home --uid 1000 app
COPY --from=build /opt/venv /opt/venv
USER app
WORKDIR /home/app

CMD ["python", "-m", "smarthack"]

# --- serving: production plus what a long-running service needs -------------------
# TODO: replace the CMD with the real server once the application chooses one
# (for example uvicorn), and add its package to a `serving` extra in pyproject.toml.
FROM production AS serving

ENV PORT=8000
EXPOSE 8000

CMD ["python", "-m", "smarthack"]
