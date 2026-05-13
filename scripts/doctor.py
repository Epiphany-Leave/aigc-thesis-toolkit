#!/usr/bin/env python3
"""Check whether common runtime dependencies are available."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys


COMMANDS = {
    "python": [sys.executable, "--version"],
    "pandoc": ["pandoc", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "libreoffice": ["libreoffice", "--version"],
    "pdftotext": ["pdftotext", "-v"],
    "antiword": ["antiword", "-h"],
    "catdoc": ["catdoc", "-V"],
    "tesseract": ["tesseract", "--version"],
}

PYTHON_MODULES = ["yaml", "pypandoc", "pptx"]


def command_status(name: str, command: list[str]) -> tuple[bool, str]:
    if name == "pandoc":
        bundled = bundled_pandoc()
        if bundled:
            return True, str(bundled)
    executable = shutil.which(command[0])
    if not executable:
        return False, "not found"
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=8)
    except Exception as exc:  # noqa: BLE001 - diagnostic helper.
        return False, str(exc)
    first_line = (result.stdout or "").splitlines()[0] if result.stdout else executable
    return True, first_line


def bundled_pandoc() -> Path | None:
    spec = importlib.util.find_spec("pypandoc")
    if not spec or not spec.origin:
        return None
    executable = Path(spec.origin).parent / "files" / ("pandoc.exe" if os.name == "nt" else "pandoc")
    return executable if executable.exists() else None


def module_status(name: str) -> tuple[bool, str]:
    spec = importlib.util.find_spec(name)
    return (spec is not None, "installed" if spec else "not found")


def main() -> int:
    failed = False
    print("Python modules:")
    for name in PYTHON_MODULES:
        ok, detail = module_status(name)
        failed = failed or not ok
        print(f"  {'OK' if ok else 'MISS'} {name}: {detail}")

    print("\nSystem commands:")
    for name, command in COMMANDS.items():
        ok, detail = command_status(name, command)
        failed = failed or not ok
        print(f"  {'OK' if ok else 'MISS'} {name}: {detail}")

    if failed:
        print("\nSome dependencies are missing. On Ubuntu/WSL run:")
        print("  bash scripts/install_system_deps_ubuntu.sh")
        print("  python -m pip install -r requirements.txt")
        print("  cd workflows/webui/frontend && npm install && npm run build")
        return 1
    print("\nOK: dependency check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
