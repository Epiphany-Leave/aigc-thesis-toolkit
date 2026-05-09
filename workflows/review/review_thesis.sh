#!/bin/bash
# Prepare a review task for the assembled thesis.
#
# This script intentionally does not run an AI review by itself. It checks
# inputs and prints the files that should be given to the review agent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="$WORK/configs/default.yaml"
read_config() {
    python3 - "$CONFIG" "$1" <<'PY'
import sys, yaml
config_path, dotted = sys.argv[1], sys.argv[2]
with open(config_path, "r", encoding="utf-8") as handle:
    data = yaml.safe_load(handle) or {}
value = data
for part in dotted.split("."):
    value = value.get(part, {}) if isinstance(value, dict) else {}
print(value if isinstance(value, (str, int, float)) else "")
PY
}

SRC="$WORK/$(read_config review.input_markdown)"
PROMPT="$WORK/$(read_config review.prompt)"
REPORT="$WORK/$(read_config review.output_report)"

if [ ! -f "$SRC" ]; then
    echo "ERROR: $SRC not found. Run: bash workflows/write/build_markdown.sh"
    exit 1
fi

if [ ! -f "$PROMPT" ]; then
    echo "ERROR: $PROMPT not found"
    exit 1
fi

echo "Review input: $SRC"
echo "Review prompt: $PROMPT"
echo "Suggested output: $REPORT"
