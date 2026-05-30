#!/bin/sh
set -e

# ---- Download bundled databases from Supabase Storage ------------------
if [ -n "${SUPABASE_SERVICE_KEY}" ] && [ -n "${SUPABASE_PROJECT_REF}" ]; then
  echo "Fetching bundled databases from Supabase Storage..."
  DB_DIR="/app/Databases"
  mkdir -p "${DB_DIR}"
  BASE="https://${SUPABASE_PROJECT_REF}.supabase.co/storage/v1/object/bundled-dbs"

  for f in california_schools.sqlite debit_card_specializing.sqlite \
           formula_1.sqlite toxicology.sqlite \
           financial.sqlite.gz european_football_2.sqlite.gz; do
    echo "  → ${f}"
    python3 -c "
import urllib.request, os
url = '${BASE}/${f}'
req = urllib.request.Request(url, headers={'Authorization': 'Bearer ${SUPABASE_SERVICE_KEY}'})
with urllib.request.urlopen(req) as r, open('${DB_DIR}/${f}', 'wb') as w:
    w.write(r.read())
print(f'    downloaded {os.path.getsize(\"${DB_DIR}/${f}\")} bytes')
"
    case "${f}" in
      *.gz) gunzip -f "${DB_DIR}/${f}"; echo "    decompressed" ;;
    esac
  done
  echo "Bundled databases ready ($(ls -1 ${DB_DIR}/*.sqlite 2>/dev/null | wc -l) files)."
else
  echo "SUPABASE_SERVICE_KEY or SUPABASE_PROJECT_REF not set — skipping DB fetch."
fi

# ---- Run database migrations -------------------------------------------
echo "Running DB migrations..."
cd /app
python -m alembic -c alembic.ini upgrade head
echo "Migrations complete."

exec uvicorn insightxpert_api.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'
