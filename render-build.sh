#!/usr/bin/env bash
set -e

echo "==> Cleaning apt cache..."
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

echo "==> Installing Google Chrome stable..."
apt-get update -qq
apt-get install -y -qq wget gnupg ca-certificates apt-transport-https fonts-liberation libasound2 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo-gobject2 libgtk-3-0

# Modern GPG key + repo (no deprecated apt-key)
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

apt-get update -qq
apt-get install -y -qq google-chrome-stable

# Strict cleanup to avoid partial lists error
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

echo "==> Chrome version:"
google-chrome-stable --version

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Build complete."