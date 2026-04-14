#!/usr/bin/env bash
# Start both the Node.js WhatsApp sidecar and the Python FastAPI server.
# Used as the Render "Start Command".

set -e

echo "Starting WhatsApp sidecar on port 3001…"
cd wa-service && node index.js &
WA_PID=$!
cd ..

# Give the Node service a moment to bind
sleep 2

echo "Starting FastAPI on port $PORT…"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
