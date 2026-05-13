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

$SUDO apt-get update
$SUDO apt-get install -y \
    nodejs \
    npm \
    libreoffice \
    poppler-utils \
    antiword \
    catdoc \
    tesseract-ocr \
    tesseract-ocr-chi-sim

echo "OK: system dependencies installed."
echo "Tip: Node.js from Ubuntu's default apt repository may be older on some releases."
echo "If npm run build reports that Node.js is too old, install Node.js 18+ from NodeSource or nvm."
