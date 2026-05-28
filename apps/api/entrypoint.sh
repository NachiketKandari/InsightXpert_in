#!/bin/sh
set -e

# Run database migration before starting uvicorn.
# Standalone — avoids hanging inside uvicorn's lifespan thread pool.
echo "Running DB migrations..."
cd /app
python -m alembic -c alembic.ini upgrade head
echo "Migrations complete."

exec uvicorn insightxpert_api.main:app --host 0.0.0.0 --port ${PORT:-8080}
