#!/usr/bin/env bash
set -e

echo "==> Starting Render build..."

if command -v google-chrome >/dev/null 2>&1; then
  echo "==> Chrome found: $(google-chrome --version)"
elif command -v google-chrome-stable >/dev/null 2>&1; then
  echo "==> Chrome found: $(google-chrome-stable --version)"
else
  echo "==> Chrome not available during build. Render must provide it at runtime."
fi

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Build complete."
