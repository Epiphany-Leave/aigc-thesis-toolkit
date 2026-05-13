#!/usr/bin/env bash
# Install non-Python system dependencies for Ubuntu/WSL.

set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
    echo "ERROR: apt-get not found. This helper supports Ubuntu/Debian/WSL only." >&2
    echo "Please install equivalent packages manually: Node.js 18+, npm, LibreOffice, poppler-utils, antiword, catdoc, tesseract OCR, and Chinese OCR data." >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

node_major() {
    if ! command -v node >/dev/null 2>&1; then
        echo 0
        return
    fi
    node --version | sed -E 's/^v([0-9]+).*/\1/'
}

$SUDO apt-get update
$SUDO apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    libreoffice \
    poppler-utils \
    antiword \
    catdoc \
    tesseract-ocr \
    tesseract-ocr-chi-sim

if [ "$(node_major)" -lt 18 ]; then
    echo "Installing Node.js 20 from NodeSource because Vite requires Node.js 18+..."
    $SUDO install -d -m 0755 /etc/apt/keyrings
    $SUDO rm -f /etc/apt/keyrings/nodesource.gpg
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | $SUDO gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        | $SUDO tee /etc/apt/sources.list.d/nodesource.list >/dev/null
    $SUDO apt-get update
    $SUDO apt-get install -y nodejs
fi

if [ "$(node_major)" -lt 18 ]; then
    echo "ERROR: Node.js is still older than 18. Please install Node.js 18+ with nvm or NodeSource." >&2
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    $SUDO apt-get install -y npm
fi

echo "OK: system dependencies installed."
echo "Node: $(node --version)"
echo "npm: $(npm --version)"
