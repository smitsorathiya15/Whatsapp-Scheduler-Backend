#!/usr/bin/env bash
# Render build step — install Python + Node.js + Chromium for Puppeteer
set -o errexit

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Installing Node.js WhatsApp sidecar dependencies ==="
cd wa-service
npm install



cd ..
echo "=== Build complete ==="
