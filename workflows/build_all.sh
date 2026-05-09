#!/bin/bash
# Assemble Markdown and export the final DOCX.
#
# Usage:
#   bash workflows/build_all.sh
#   bash workflows/build_all.sh --no-assemble

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ "${1:-}" != "--no-assemble" ]; then
    bash "$WORK/workflows/write/build_markdown.sh"
fi

bash "$WORK/workflows/export_docx/build_docx.sh"
