#!/usr/bin/env bash
# Fetch bundled BIRD sample SQLite DBs into apps/api/Databases/_shared/.
# Dev: rsync from the local Private/InsightXpert reference repo.
# CI/Docker: override SOURCE_DIR with a GCS sync or artifact download.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${SCRIPT_DIR}/../Databases/_shared"
SOURCE_DIR="${BUNDLED_DBS_SOURCE:-/Users/nachiket/workspace/github.com/Private/InsightXpert/Databases}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "ERROR: source dir not found: ${SOURCE_DIR}" >&2
  echo "Set BUNDLED_DBS_SOURCE to override." >&2
  exit 1
fi

mkdir -p "${DEST_DIR}"
rsync -a --include='*.sqlite' --exclude='*' "${SOURCE_DIR}/" "${DEST_DIR}/"
echo "Fetched $(ls -1 "${DEST_DIR}"/*.sqlite 2>/dev/null | wc -l | tr -d ' ') SQLite samples → ${DEST_DIR}"
