#!/usr/bin/env bash
# Seed the toxicology_pg database in Supabase from the bundled SQLite file.
# Idempotent: drops and recreates the `toxicology` schema on each run.
#
# Prereq: DATABASE_URL_TOXICOLOGY_PG must be set — see apps/api/.env.example
#         (in dev, put it in apps/api/.env.local and `set -a && source .env.local && set +a` first).

set -euo pipefail

: "${DATABASE_URL_TOXICOLOGY_PG:?DATABASE_URL_TOXICOLOGY_PG must be set — see apps/api/.env.example}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SQLITE="$API_DIR/Databases/_shared/toxicology.sqlite"

if [[ ! -f "$SQLITE" ]]; then
    echo "toxicology.sqlite not present — fetching bundled databases..."
    (cd "$API_DIR" && ./scripts/fetch-bundled-dbs.sh)
fi

echo "running sqlite → postgres conversion..."
cd "$API_DIR"
uv run python -m insightxpert_api.scripts.sqlite_to_postgres \
    --sqlite "$SQLITE" \
    --pg-url "$DATABASE_URL_TOXICOLOGY_PG" \
    --pg-schema toxicology \
    --drop-existing

echo "done. verify with:"
echo "  psql \"\$DATABASE_URL_TOXICOLOGY_PG\" -c \"SELECT COUNT(*) FROM toxicology.molecule;\""
