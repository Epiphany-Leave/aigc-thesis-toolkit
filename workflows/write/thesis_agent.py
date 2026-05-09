#!/usr/bin/env python3
"""Manage thesis section state and assemble thesis/sections into output/thesis.md."""

import datetime
import json
import sys
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"


def load_config():
    config = {}
    if CONFIG_FILE.exists():
        config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    if LOCAL_CONFIG_FILE.exists():
        config = deep_merge(config, yaml.safe_load(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) or {})
    return config


def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    result = dict(base)
    for key, value in override.items():
        result[key] = deep_merge(result.get(key), value) if key in result else value
    return result


CONFIG = load_config()
PATHS = CONFIG.get("paths", {})
ASSEMBLY = CONFIG.get("assembly", {})

BASE = WORK / PATHS.get("thesis_dir", "thesis")
OUTPUT_DIR = WORK / PATHS.get("output_dir", "output")
STATE_FILE = BASE / "state.json"
PLAN_FILE = WORK / ASSEMBLY.get("plan_file", "thesis/section_plan.json")
THESIS_FILE = WORK / ASSEMBLY.get("output_markdown", "output/thesis.md")

THESIS_TITLE = CONFIG.get("project", {}).get("title", "未命名论文")
DEFAULT_SECTION_ORDER = [
    "sections/00_abstract.md",
    "sections/01_introduction.md",
    "sections/02_topology.md",
    "sections/03_steady_state.md",
    "sections/04_modeling.md",
    "sections/05_current_sharing.md",
    "sections/06_simulation.md",
    "sections/07_experiment.md",
    "sections/08_conclusion.md",
]


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_plan():
    plan = load_json(PLAN_FILE, {})
    return plan.get("sections", [])


def load_state():
    return load_json(
        STATE_FILE,
        {
            "project": THESIS_TITLE,
            "current_chapter": None,
            "next_action": "run python workflow.py plan",
            "chapters": {},
            "generation_log": [],
        },
    )


def save_state(state):
    save_json(STATE_FILE, state)


def section_rows():
    plan_sections = load_plan()
    if plan_sections:
        return plan_sections

    state = load_state()
    rows = []
    for chapter_id, chapter in state.get("chapters", {}).items():
        rows.append(
            {
                "id": chapter_id,
                "title": chapter.get("title", chapter_id),
                "file": chapter.get("file"),
                "status": chapter.get("status", "pending"),
            }
        )
    return rows


def sync_plan_status(section_id, status):
    sections = load_plan()
    if not sections:
        return False
    changed = False
    for item in sections:
        if item.get("id") == section_id:
            item["status"] = status
            item["last_updated"] = datetime.datetime.now().isoformat()
            changed = True
            break
    if changed:
        save_json(PLAN_FILE, {"sections": sections})
    return changed


def cmd_status():
    state = load_state()
    rows = section_rows()

    print(f"Project: {state.get('project', THESIS_TITLE)}")
    print(f"Current section: {cmd_next(print_result=False)}")
    print(f"Plan: {PLAN_FILE if PLAN_FILE.exists() else 'not created'}")
    print("---")

    if not rows:
        print("No sections found. Run: python workflow.py plan")
        return

    for item in rows:
        status = item.get("status", "pending")
        print(f"  [{status}] {item.get('id')}: {item.get('title')}")


def cmd_next(print_result=True):
    rows = section_rows()
    for item in rows:
        if item.get("status") != "done":
            result = item.get("id")
            if print_result:
                print(result)
            return result
    if print_result:
        print("ALL_DONE")
    return "ALL_DONE"


def cmd_update(section_id, status):
    if status not in {"pending", "in_progress", "done"}:
        raise SystemExit(f"Unknown status: {status}")

    rows = section_rows()
    known_ids = {item.get("id") for item in rows}
    if rows and section_id not in known_ids:
        raise SystemExit(f"Unknown section: {section_id}")

    sync_plan_status(section_id, status)

    state = load_state()
    chapters = state.setdefault("chapters", {})
    chapter = chapters.setdefault(section_id, {})
    chapter["status"] = status
    chapter["last_updated"] = datetime.datetime.now().isoformat()

    next_id = cmd_next(print_result=False)
    state["current_chapter"] = None if next_id == "ALL_DONE" else next_id
    state["next_action"] = "all done - assemble/export" if next_id == "ALL_DONE" else f"start {next_id}"
    save_state(state)
    print(f"Updated {section_id} -> {status}")


def cmd_log(message):
    state = load_state()
    entry = {
        "time": datetime.datetime.now().isoformat(),
        "message": message,
        "chapter": state.get("current_chapter"),
    }
    state.setdefault("generation_log", []).append(entry)
    state["generation_log"] = state["generation_log"][-100:]
    save_state(state)

    log_dir = BASE / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{datetime.datetime.now():%Y-%m-%d}.log"
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{entry['time']}] [{entry['chapter']}] {message}\n")
    print(f"Logged: {message}")


def assembly_order():
    configured = ASSEMBLY.get("section_order", "auto")
    if configured == "auto":
        sections = load_plan()
        if not sections:
            raise SystemExit("ERROR: thesis section plan not found. Run: python workflow.py plan")
        return [item["file"] for item in sections if item.get("file")]
    return configured or DEFAULT_SECTION_ORDER


def cmd_assemble():
    OUTPUT_DIR.mkdir(exist_ok=True)
    parts = [f"# {THESIS_TITLE}\n"]
    plan_by_file = {item.get("file"): item for item in load_plan()}
    current_chapter = None

    for relative in assembly_order():
        path = BASE / relative
        if not path.exists():
            print(f"WARN: missing section: {path}", file=sys.stderr)
            continue
        item = plan_by_file.get(relative, {})
        chapter_title = item.get("chapter_title")
        subsection_title = item.get("subsection_title")
        if subsection_title and chapter_title and chapter_title != current_chapter:
            parts.append(f"# {chapter_title}")
            current_chapter = chapter_title
        content = path.read_text(encoding="utf-8-sig").strip()
        if content:
            parts.append(content)

    THESIS_FILE.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    print(f"Assembled -> {THESIS_FILE}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    command = sys.argv[1]
    if command == "status":
        cmd_status()
    elif command == "next":
        cmd_next()
    elif command == "update" and len(sys.argv) == 4:
        cmd_update(sys.argv[2], sys.argv[3])
    elif command == "log" and len(sys.argv) >= 3:
        cmd_log(" ".join(sys.argv[2:]))
    elif command == "assemble":
        cmd_assemble()
    else:
        print(f"Unknown or incomplete command: {' '.join(sys.argv[1:])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
