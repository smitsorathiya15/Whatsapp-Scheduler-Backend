#!/usr/bin/env bash
# Render start command — launches the Node.js WhatsApp sidecar then FastAPI.
set -e

export WA_SERVICE_PORT="${WA_SERVICE_PORT:-3001}"
export WA_SERVICE_URL="http://localhost:${WA_SERVICE_PORT}"

echo "==> Starting WhatsApp sidecar on port ${WA_SERVICE_PORT}…"
cd wa-service
node index.js &
WA_PID=$!
cd ..

# Wait for the sidecar to be ready
echo "==> Waiting for sidecar to be ready…"
for i in $(seq 1 15); do
  if curl -sf "http://localhost:${WA_SERVICE_PORT}/health" > /dev/null 2>&1; then
    echo "==> Sidecar is ready."
    break
  fi
  sleep 1
done

echo "==> Starting FastAPI on port ${PORT:-10000}…"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-10000}"
