#!/bin/bash
# Export output/thesis.md to output/thesis.docx.

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

SRC="$WORK/$(read_config export_docx.input_markdown)"
TMP="/tmp/thesis_export.md"
DST="$WORK/$(read_config export_docx.output_docx)"
DST_ALT="$WORK/$(read_config export_docx.fallback_docx)"
REFERENCE_DOC="$WORK/$(read_config paths.template_docx)"
TOC_DEPTH="$(read_config export_docx.toc_depth)"
TOC_DEPTH="${TOC_DEPTH:-3}"

if [ ! -f "$SRC" ]; then
    echo "ERROR: $SRC not found. Run: bash workflows/write/build_markdown.sh"
    exit 1
fi

if [ ! -f "$REFERENCE_DOC" ]; then
    echo "ERROR: $REFERENCE_DOC not found"
    exit 1
fi

python3 "$WORK/workflows/export_docx/prepare_docx_markdown.py" "$SRC" "$TMP"

PANDOC=$(python3 -c "import pypandoc; import os; print(os.path.join(os.path.dirname(pypandoc.__file__), 'files', 'pandoc'))" 2>/dev/null)

if [ -z "$PANDOC" ] || [ ! -f "$PANDOC" ]; then
    PANDOC=$(which pandoc 2>/dev/null)
fi

if [ -z "$PANDOC" ] || [ ! -f "$PANDOC" ]; then
    echo "ERROR: pandoc not found"
    exit 1
fi

DST_TMP="/tmp/thesis_output.docx"
"$PANDOC" "$TMP" \
    -f markdown \
    -t docx \
    --standalone \
    --reference-doc="$REFERENCE_DOC" \
    --toc \
    --toc-depth="$TOC_DEPTH" \
    -o "$DST_TMP"

if cp -f "$DST_TMP" "$DST" 2>/dev/null; then
    python3 "$WORK/workflows/export_docx/postprocess_docx.py" "$DST"
    SIZE=$(stat -c%s "$DST")
    echo "OK: $DST ($SIZE bytes)"
else
    cp -f "$DST_TMP" "$DST_ALT"
    python3 "$WORK/workflows/export_docx/postprocess_docx.py" "$DST_ALT"
    SIZE=$(stat -c%s "$DST_ALT")
    echo "OK: $DST_ALT ($SIZE bytes) [original locked]"
fi

rm -f "$DST_TMP" "$TMP"
