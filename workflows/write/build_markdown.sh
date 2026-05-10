#!/bin/bash
# Assemble thesis/sections into output/thesis.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(cd "$SCRIPT_DIR/../.." && pwd)"

python3 "$WORK/workflows/write/generate_references.py" --overwrite
python3 "$WORK/workflows/write/thesis_agent.py" assemble

RUN_GATE=$(python3 - "$WORK/configs/default.yaml" <<'PY'
import sys, yaml
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    config = yaml.safe_load(handle) or {}
gate = config.get("engines", {}).get("quality_gate", {})
print("1" if gate.get("rule_based", True) and gate.get("run_after_assemble", True) else "0")
PY
)

if [ "$RUN_GATE" = "1" ]; then
    python3 "$WORK/workflows/write/quality_gate.py"
fi
