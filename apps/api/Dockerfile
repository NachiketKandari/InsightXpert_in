# syntax=docker/dockerfile:1.7
# Multi-stage build: uv-managed deps in the build stage, slim runtime.
# Build context is apps/api/.

ARG PYTHON_VERSION=3.12

# ---- build stage ----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS build

# Copy uv from the official minimal image (pinned by digest in CI if desired).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Leverage the dep-only layer cache: copy lockfile + pyproject first.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then copy sources and sync again to install the project itself.
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY few_shot/ ./few_shot/
COPY entrypoint.sh ./
RUN uv sync --frozen --no-dev

# Bundled sample DBs: copied last so code changes don't bust the DB layer.
# In CI, fetch these from GCS before `docker build` using scripts/fetch-bundled-dbs.sh
# (or mount a build arg). For local builds, the rsync in that script populates Databases/.
COPY Databases/ ./Databases/

# ---- runtime stage --------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# Non-root user for defense-in-depth. Cloud Run doesn't mandate it, but it's cheap.
RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app

WORKDIR /app
COPY --from=build --chown=app:app /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    APP_ENV=prod

USER app
EXPOSE 8080

# Run migrations before starting uvicorn (avoids asyncio lifespan hang).
CMD ["sh", "/app/entrypoint.sh"]
