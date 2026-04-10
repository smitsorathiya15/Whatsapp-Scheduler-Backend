#!/usr/bin/env bash
set -e

echo "==> Installing Google Chrome stable..."
apt-get update -qq
apt-get install -y -qq wget gnupg ca-certificates apt-transport-https

# Add Google's signing key and repo
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list

apt-get update -qq
apt-get install -y -qq google-chrome-stable

echo "==> Chrome version:"
google-chrome-stable --version

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Build complete."
