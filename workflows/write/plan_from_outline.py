#!/usr/bin/env python3
"""Create thesis/section_plan.json from thesis/outline.md."""

import argparse
import json
import re
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"

LEGACY_FILES = {
    0: "sections/00_abstract.md",
    1: "sections/01_introduction.md",
    2: "sections/02_topology.md",
    3: "sections/03_steady_state.md",
    4: "sections/04_modeling.md",
    5: "sections/05_current_sharing.md",
    6: "sections/06_simulation.md",
    7: "sections/07_experiment.md",
    8: "sections/08_conclusion.md",
}
SKIP_TITLES = {"参考文献", "致谢", "目录"}


def load_config():
    if not CONFIG_FILE.exists():
        return {}
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


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(text):
    text = re.sub(r"^第\s*[0-9一二三四五六七八九十]+\s*章\s*", "", text).strip()
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", text).strip("_")
    return text[:32] or "section"


def is_abstract(title):
    lowered = title.lower()
    return "摘要" in title or lowered in {"abstract", "chinese abstract", "english abstract"}


def section_id(index, title):
    if is_abstract(title):
        return "ch0_abstract"
    return f"ch{index:02d}_{slugify(title)}"


def subsection_id(chapter_index, subsection_index, title):
    return f"ch{chapter_index:02d}_sec{subsection_index:02d}_{slugify(title)}"


def section_file(thesis_dir, index, title, subsection_index=None, subsection_title=None):
    if is_abstract(title):
        if subsection_index is not None:
            return f"sections/00_{subsection_index:02d}_{slugify(subsection_title or title)}.md"
        return "sections/00_abstract.md"

    legacy = LEGACY_FILES.get(index)
    if subsection_index is None and legacy and (thesis_dir / legacy).exists():
        return legacy

    if subsection_index is not None:
        return f"sections/{index:02d}_{subsection_index:02d}_{slugify(subsection_title or title)}.md"
    return f"sections/{index:02d}_{slugify(title)}.md"


def parse_outline(outline_text):
    chapters = []
    current = None
    for line in outline_text.splitlines():
        chapter_match = re.match(r"^##\s+(.+?)\s*$", line)
        if chapter_match:
            title = chapter_match.group(1).strip()
            if title in SKIP_TITLES:
                current = None
                continue
            current = {"title": title, "subsections": []}
            chapters.append(current)
            continue

        subsection_match = re.match(r"^###\s+(.+?)\s*$", line)
        if not subsection_match or current is None:
            continue
        subtitle = subsection_match.group(1).strip()
        if subtitle and subtitle not in SKIP_TITLES:
            current["subsections"].append(subtitle)
    return chapters


def existing_status(thesis_dir, existing_plan, existing_state, section_id_value, file_value):
    existing_file = thesis_dir / file_value
    for item in existing_plan.get("sections", []):
        if item.get("id") == section_id_value or item.get("file") == file_value:
            status = item.get("status", "pending")
            if status == "done" or not existing_file.exists():
                return status
            if existing_file.read_text(encoding="utf-8-sig").strip():
                return "done"
            return status

    chapters = existing_state.get("chapters", {})
    for key, item in chapters.items():
        if key == section_id_value or item.get("file") == file_value:
            status = item.get("status", "pending")
            if status == "done" or not existing_file.exists():
                return status
            if existing_file.read_text(encoding="utf-8-sig").strip():
                return "done"
            return status

    if existing_file.exists() and existing_file.read_text(encoding="utf-8-sig").strip():
        return "done"
    return "pending"


def natural_key(path):
    parts = re.split(r"(\d+)", path.stem)
    return [int(part) if part.isdigit() else part for part in parts]


def extra_section_files(thesis_dir, index, main_file):
    sections_dir = thesis_dir / "sections"
    if not sections_dir.exists() or index <= 0:
        return []

    prefix = f"{index:02d}_"
    extras = []
    for path in sections_dir.glob(f"{prefix}*.md"):
        relative = path.relative_to(thesis_dir).as_posix()
        if relative == main_file:
            continue
        extras.append(relative)
    return sorted(extras, key=lambda item: natural_key(Path(item)))


def make_item(thesis_dir, chapter_index, chapter_title, existing_plan, existing_state, subsection_index=None, subsection_title=None):
    title = subsection_title or chapter_title
    if subsection_index is None:
        file_value = section_file(thesis_dir, chapter_index, chapter_title)
        id_value = section_id(chapter_index, chapter_title)
    else:
        file_value = section_file(thesis_dir, chapter_index, chapter_title, subsection_index, subsection_title)
        id_value = subsection_id(chapter_index, subsection_index, subsection_title)

    return {
        "id": id_value,
        "title": title,
        "chapter_title": chapter_title,
        "subsection_title": subsection_title,
        "file": file_value,
        "status": existing_status(thesis_dir, existing_plan, existing_state, id_value, file_value),
    }


def make_plan(thesis_dir, chapters, existing_plan, existing_state, granularity="chapter"):
    plan = []
    chapter_index = 0
    chapter_mode = granularity != "subsection"
    for chapter in chapters:
        chapter_title = chapter["title"]
        if is_abstract(chapter_title):
            index = 0
        else:
            chapter_index += 1
            index = chapter_index

        subsections = chapter.get("subsections") or []
        if subsections and chapter_mode:
            item = make_item(thesis_dir, index, chapter_title, existing_plan, existing_state)
            item["subsections"] = subsections
            item["generation_granularity"] = "chapter"
            plan.append(item)
            continue

        if subsections:
            for subsection_index, subsection_title in enumerate(subsections, start=1):
                item = make_item(
                    thesis_dir,
                    index,
                    chapter_title,
                    existing_plan,
                    existing_state,
                    subsection_index,
                    subsection_title,
                )
                item["generation_granularity"] = "subsection"
                plan.append(item)
            continue

        item = make_item(thesis_dir, index, chapter_title, existing_plan, existing_state)
        item["generation_granularity"] = "chapter" if chapter_mode else "subsection"
        plan.append(item)

        for extra_file in extra_section_files(thesis_dir, index, plan[-1]["file"]):
            extra_id = f"ch{index:02d}_{Path(extra_file).stem}"
            plan.append(
                {
                    "id": extra_id,
                    "title": f"{chapter_title} - {Path(extra_file).stem}",
                    "chapter_title": chapter_title,
                    "subsection_title": Path(extra_file).stem,
                    "file": extra_file,
                    "status": existing_status(thesis_dir, existing_plan, existing_state, extra_id, extra_file),
                }
            )
    return plan


def write_state(thesis_dir, title, plan, overwrite=False):
    state_path = thesis_dir / "state.json"
    if state_path.exists() and not overwrite:
        return False

    chapters = {
        item["id"]: {
            "status": item["status"],
            "file": item["file"],
            "title": item["title"],
        }
        for item in plan
    }
    next_item = next((item for item in plan if item["status"] != "done"), None)
    state = {
        "project": title,
        "current_chapter": next_item["id"] if next_item else None,
        "next_action": f"start {next_item['id']}" if next_item else "all done - assemble/export",
        "chapters": chapters,
        "generation_log": [],
    }
    write_json(state_path, state)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite-state", action="store_true")
    args = parser.parse_args()

    config = load_config()
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    outline_path = thesis_dir / "outline.md"
    plan_path = WORK / config.get("assembly", {}).get("plan_file", "thesis/section_plan.json")
    project_title = config.get("project", {}).get("title", "未命名论文")

    if not outline_path.exists():
        raise SystemExit(f"ERROR: outline not found: {outline_path}")

    chapters = parse_outline(outline_path.read_text(encoding="utf-8-sig"))
    if not chapters:
        raise SystemExit("ERROR: no level-2 headings found in thesis/outline.md")

    existing_plan = load_json(plan_path, {})
    existing_state = load_json(thesis_dir / "state.json", {})
    granularity = config.get("engines", {}).get("generation", {}).get("granularity", "chapter")
    plan = make_plan(thesis_dir, chapters, existing_plan, existing_state, granularity)
    write_json(plan_path, {"generation_granularity": granularity, "sections": plan})
    write_state(thesis_dir, project_title, plan, overwrite=args.overwrite_state)

    print(f"OK: plan -> {plan_path}")
    for item in plan:
        print(f"  {item['file']}  {item['title']}")


if __name__ == "__main__":
    raise SystemExit(main())
