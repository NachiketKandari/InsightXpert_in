#!/usr/bin/env bash
# Sync the `transactions` Turso database down to a local SQLite file
# at apps/api/Databases/_shared/transactions.sqlite.
#
# Turso is the source of truth; this produces a local read-only mirror that
# the pipeline consumes as a bundled DB (same treatment as the BIRD samples).
# Re-run whenever upstream rows change.
#
# Requires `turso` CLI on PATH and an active auth session (`turso auth login`).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SCRIPT_DIR}/../Databases/_shared/transactions.sqlite"
DB_NAME="${TURSO_TRANSACTIONS_DB:-transactions}"

command -v turso >/dev/null || { echo "turso CLI not found on PATH" >&2; exit 1; }
command -v sqlite3 >/dev/null || { echo "sqlite3 CLI not found on PATH" >&2; exit 1; }

TMP_SQL="$(mktemp -t turso-transactions.XXXXXX.sql)"
trap 'rm -f "$TMP_SQL"' EXIT

echo "Dumping Turso DB '${DB_NAME}' → ${TMP_SQL}"
turso db shell "${DB_NAME}" ".dump" > "$TMP_SQL"

mkdir -p "$(dirname "$DEST")"
rm -f "$DEST"
sqlite3 "$DEST" < "$TMP_SQL"

ROWS=$(sqlite3 "$DEST" 'SELECT COUNT(*) FROM transactions')
SIZE=$(du -h "$DEST" | cut -f1)
echo "Synced ${ROWS} rows (${SIZE}) → ${DEST}"
