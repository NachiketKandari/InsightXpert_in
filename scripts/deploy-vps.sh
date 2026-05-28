#!/usr/bin/env bash
# insightxpert.in — VPS Backend Setup Script
# Run this ON your Hostinger VPS as root (ssh root@187.127.166.171)
set -euo pipefail

echo "=== 1. Install Docker ==="
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  systemctl enable docker
  echo "Docker installed."
else
  echo "Docker already installed: $(docker --version)"
fi

echo ""
echo "=== 2. Create app directory structure ==="
mkdir -p /opt/insightxpert/{Databases,indices,storage}
cd /opt/insightxpert

echo ""
echo "=== 3. Clone repo and build Docker image ==="
if [ ! -d /opt/insightxpert/repo ]; then
  git clone https://github.com/NachiketKandari/InsightXpert.in.git /opt/insightxpert/repo
fi
cd /opt/insightxpert/repo
git pull origin main
cd apps/api

echo ""
echo "=== 4. Build Docker image ==="
docker build -t insightxpert-api:latest .

echo ""
echo "=== 5. Create the .env file ==="
# You MUST edit this file with your real values before starting the container!
cat > /opt/insightxpert/.env << 'ENVEOF'
# --- Runtime ---
APP_ENV=production
PORT=8080

# --- CORS (update if using a different frontend domain) ---
CORS_ORIGINS='["https://insightxpert.in","https://www.insightxpert.in"]'

# --- Supabase (use YOUR real values from 1Password / previous .env) ---
DATABASE_URL=postgresql+psycopg://postgres.rwnxgohpmmuyfjeghhaj:<YOUR_SUPABASE_PASSWORD>@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres
DATABASE_DIRECT_URL=postgresql+psycopg://postgres:<YOUR_SUPABASE_PASSWORD>@db.rwnxgohpmmuyfjeghhaj.supabase.co:5432/postgres?sslmode=require

# --- Auth ---
SESSION_SECRET=<GENERATE_A_RANDOM_32_CHAR_STRING>
BOOTSTRAP_ADMIN_EMAIL=admin@insightxpert.ai
BOOTSTRAP_ADMIN_PASSWORD=<SET_A_STRONG_ADMIN_PASSWORD>
BOOTSTRAP_USER_EMAIL=user@insightxpert.ai
BOOTSTRAP_USER_PASSWORD=<SET_A_STRONG_USER_PASSWORD>
REGISTRATION_ENABLED=true

# --- LLM ---
LLM_PROVIDER=deepseek
GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>
DEEPSEEK_API_KEY=<YOUR_DEEPSEEK_API_KEY>

# --- Paths ---
BUNDLED_DBS_DIR=/opt/insightxpert/Databases
INDICES_DIR=/opt/insightxpert/indices
LOCAL_STORAGE_DIR=/opt/insightxpert/storage

# --- Pipeline ---
MAX_UPLOAD_MB=50
SQL_ROW_LIMIT=1000
SQL_TIMEOUT_SECONDS=30

# --- Encryption (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") ---
CREDENTIAL_ENCRYPTION_KEY=<GENERATE_A_FERNET_KEY>

# --- Observability ---
SENTRY_DSN=<YOUR_SENTRY_DSN>
SENTRY_TRACES_SAMPLE_RATE=0.1
ENVEOF

echo ".env template written to /opt/insightxpert/.env"
echo ">>> EDIT /opt/insightxpert/.env WITH YOUR REAL VALUES <<<"

echo ""
echo "=== 6. Copy bundled databases ==="
if [ -d /opt/insightxpert/repo/apps/api/Databases ]; then
  cp -r /opt/insightxpert/repo/apps/api/Databases/* /opt/insightxpert/Databases/
  echo "Bundled databases copied."
fi

echo ""
echo "=== 7. Create docker-compose.yml ==="
cat > /opt/insightxpert/docker-compose.yml << 'COMPOSEEOF'
version: "3.8"
services:
  api:
    image: insightxpert-api:latest
    ports:
      - "127.0.0.1:8080:8080"
    env_file:
      - /opt/insightxpert/.env
    volumes:
      - /opt/insightxpert/Databases:/app/Databases:ro
      - /opt/insightxpert/indices:/app/indices
      - /opt/insightxpert/storage:/app/tmp/storage
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
COMPOSEEOF

echo ""
echo "=== 8. Install nginx ==="
if ! command -v nginx &>/dev/null; then
  apt-get update -qq && apt-get install -y -qq nginx
fi

cat > /etc/nginx/sites-available/insightxpert << 'NGINXEOF'
server {
    listen 80;
    server_name api.insightxpert.in;

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support — disable buffering for streaming responses
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/insightxpert /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "nginx configured."

echo ""
echo "=== 9. Install certbot and get SSL ==="
if ! command -v certbot &>/dev/null; then
  apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
fi
certbot --nginx -d api.insightxpert.in --non-interactive --agree-tos --email admin@insightxpert.in || echo "Certbot failed — DNS for api.insightxpert.in may not be set up yet. Run this step after DNS is configured:"
echo "  certbot --nginx -d api.insightxpert.in"

echo ""
echo "=== 10. Start the container ==="
cd /opt/insightxpert
docker compose up -d

echo ""
echo "=== Done! ==="
echo "Check: curl https://api.insightxpert.in/api/v1/health"
echo "(Or: curl http://localhost:8080/api/v1/health on the VPS)"
echo ""
echo "=== IMPORTANT: Before running this script ==="
echo "1. Edit /opt/insightxpert/.env with your real secrets"
echo "2. Point DNS A record for api.insightxpert.in → $(curl -s ifconfig.me || echo 'YOUR_VPS_IP')"
echo "3. Wait for DNS to propagate before running certbot"
