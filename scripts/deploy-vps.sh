#!/usr/bin/env bash
# insightxpert.in — VPS Backend Setup Script (NEW backend on port 8080)
# Run this ON your Hostinger VPS as nachiket
set -euo pipefail

APP_BASE="/home/nachiket/services/insightxpert-api"

echo "=== 1. Create app directory structure ==="
mkdir -p "${APP_BASE}"/{Databases,indices,storage}
cd "${APP_BASE}"

echo ""
echo "=== 2. Clone repo ==="
if [ ! -d "${APP_BASE}/repo" ]; then
  git clone git@github.com:NachiketKandari/InsightXpert.in.git "${APP_BASE}/repo"
fi
cd "${APP_BASE}/repo"
git pull origin main
cd apps/api

echo ""
echo "=== 3. Build Docker image ==="
docker build -t insightxpert-api:latest .

echo ""
echo "=== 4. Create the .env file ==="
cat > "${APP_BASE}/.env" << 'ENVEOF'
# --- Runtime ---
APP_ENV=production
PORT=8080

# --- CORS (update if using a different frontend domain) ---
CORS_ORIGINS='["https://insightxpert.in","https://www.insightxpert.in"]'

# --- Supabase (use YOUR real values from 1Password / previous .env) ---
DATABASE_URL=postgresql+psycopg://postgres.rwnxgohpmmuyfjeghhaj:<YOUR_SUPABASE_PASSWORD>@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres
DATABASE_DIRECT_URL=postgresql+psycopg://postgres.rwnxgohpmmuyfjeghhaj:<YOUR_SUPABASE_PASSWORD>@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres

# --- Auth ---
SESSION_SECRET=<GENERATE_A_RANDOM_32_CHAR_STRING>
BOOTSTRAP_ADMIN_EMAIL=admin@insightxpert.ai
BOOTSTRAP_ADMIN_PASSWORD=<SET_A_STRONG_ADMIN_PASSWORD>
REGISTRATION_ENABLED=true

# --- LLM ---
LLM_PROVIDER=deepseek
GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>
DEEPSEEK_API_KEY=<YOUR_DEEPSEEK_API_KEY>

# --- Paths ---
BUNDLED_DBS_DIR=/app/Databases
INDICES_DIR=/app/indices
LOCAL_STORAGE_DIR=/app/tmp/storage

# --- Pipeline ---
MAX_UPLOAD_MB=50
SQL_ROW_LIMIT=1000
SQL_TIMEOUT_SECONDS=30

# --- Encryption ---
CREDENTIAL_ENCRYPTION_KEY=<GENERATE_A_FERNET_KEY>

# --- Observability ---
SENTRY_DSN=<YOUR_SENTRY_DSN>
SENTRY_TRACES_SAMPLE_RATE=0.1
ENVEOF

echo ".env template written to ${APP_BASE}/.env"
echo ">>> EDIT ${APP_BASE}/.env WITH YOUR REAL VALUES <<<"

echo ""
echo "=== 5. Copy bundled databases ==="
if [ -d "${APP_BASE}/repo/apps/api/Databases" ]; then
  cp -r "${APP_BASE}/repo/apps/api/Databases"/* "${APP_BASE}/Databases/" 2>/dev/null || true
  echo "Bundled databases copied."
fi

echo ""
echo "=== 6. Create docker-compose.yml ==="
cat > "${APP_BASE}/docker-compose.yml" << COMPOSEEOF
services:
  api:
    image: insightxpert-api:latest
    ports:
      - "127.0.0.1:8080:8080"
    env_file:
      - ${APP_BASE}/.env
    volumes:
      - ${APP_BASE}/Databases:/app/Databases:ro
      - ${APP_BASE}/indices:/app/indices
      - ${APP_BASE}/storage:/app/tmp/storage
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
COMPOSEEOF

echo ""
echo "=== 7. Start the container ==="
cd "${APP_BASE}"
docker compose up -d

echo ""
echo "=== Done! ==="
echo "Check: curl http://localhost:8080/api/v1/health"
echo "Public: https://api.insightxpert.in/api/v1/health"
echo "(Caddy handles SSL and reverse proxy — already configured)"
