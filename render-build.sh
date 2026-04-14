#!/usr/bin/env bash
# Render build step — install Python + Node dependencies
set -o errexit

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Installing Node.js WhatsApp service dependencies ==="
cd wa-service && npm install

echo "=== Installing Chromium for Puppeteer ==="
npx puppeteer browsers install chrome
