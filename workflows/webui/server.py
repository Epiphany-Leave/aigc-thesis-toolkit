#!/usr/bin/env python3
"""Small local Web UI for the thesis workflow."""

from __future__ import annotations

import html
import errno
import json
import mimetypes
import os
import posixpath
import re
import subprocess
import sys
import threading
import time
import tempfile
import yaml
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


WORK = Path(__file__).resolve().parents[2]
PLAN_FILE = WORK / "thesis" / "section_plan.json"
PAUSE_FILE = WORK / "thesis" / "pause.flag"
OUTPUT_DOCX = WORK / "output" / "thesis.docx"
OUTPUT_MD = WORK / "output" / "thesis.md"
OUTPUT_PPTX = WORK / "output" / "thesis_presentation.pptx"
OUTPUT_DIR = WORK / "output"
PPT_DIR = WORK / "output" / "ppt"
PPT_PLAN_FILE = PPT_DIR / "plan.json"
PPT_OUTLINE_FILE = PPT_DIR / "outline.md"
PPT_PREVIEW_FILE = PPT_DIR / "preview.md"
REVIEW_REPORT = WORK / "output" / "review_results.md"
OUTLINE_FILE = WORK / "thesis" / "outline.md"
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"
STYLE_FILE = WORK / "thesis" / "style.md"
USER_DATA_DIR = WORK / "user_data"
PPT_SOURCE_DIR = USER_DATA_DIR / "ppt_source"
PPT_TEMPLATE_DIR = USER_DATA_DIR / "ppt_template"
PHOTO_DIR = WORK / "workflows" / "webui" / "photo"
FRONTEND_DIST = WORK / "workflows" / "webui" / "frontend" / "dist"
PREVIEW_LIMIT = 60000
USER_FILE_PREVIEW_LIMIT = 20


class Runner:
    def __init__(self):
        self.process = None
        self.command = []
        self.output = []
        self.started_at = None
        self.finished_at = None
        self.returncode = None
        self.lock = threading.Lock()

    def running(self):
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def start(self, command):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return False, "已有任务正在运行"
            self.command = command
            self.output = []
            self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.finished_at = None
            self.returncode = None
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            self.process = subprocess.Popen(
                command,
                cwd=WORK,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            threading.Thread(target=self._collect, daemon=True).start()
            return True, "任务已启动"

    def _collect(self):
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            with self.lock:
                self.output.append(line.rstrip())
                self.output = self.output[-300:]
        returncode = process.wait()
        with self.lock:
            self.returncode = returncode
            self.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def snapshot(self):
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return {
                "running": running,
                "command": self.command,
                "output": list(self.output[-120:]),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "returncode": self.returncode,
            }

    def stop(self):
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                return False
            process.terminate()
            return True


RUNNER = Runner()


def load_plan():
    if not PLAN_FILE.exists():
        return []
    return json.loads(PLAN_FILE.read_text(encoding="utf-8-sig")).get("sections", [])


def status_payload():
    rows = load_plan()
    done = sum(1 for item in rows if item.get("status") == "done")
    current = next((item for item in rows if item.get("status") != "done"), None)
    runner = RUNNER.snapshot()
    return {
        "project": read_project_title(),
        "done": done,
        "total": len(rows),
        "current": current,
        "sections": rows,
        "paused": PAUSE_FILE.exists(),
        "output_docx": OUTPUT_DOCX.exists(),
        "output_md": OUTPUT_MD.exists(),
        "output_pptx": OUTPUT_PPTX.exists(),
        "review_report": REVIEW_REPORT.exists(),
        "downloads": list_downloads(),
        "runner": runner,
        "review_progress": parse_review_progress(runner.get("output", [])),
        "ppt": ppt_payload(runner),
        "config": load_settings(),
        "style": STYLE_FILE.read_text(encoding="utf-8") if STYLE_FILE.exists() else "",
        "user_files": list_user_files(),
        "preview": live_preview(),
        "outline": read_text_file(OUTLINE_FILE),
        "thesis_logs": thesis_logs(),
        "latest_log": latest_log_text(),
    }


def parse_review_progress(output):
    progress = {"active": False, "done": 0, "total": 0, "percent": 0, "label": ""}
    for line in output:
        total_match = re.search(r"REVIEW TOTAL:\s*(\d+)", line)
        if total_match:
            progress["active"] = True
            progress["total"] = int(total_match.group(1))
        progress_match = re.search(r"REVIEW PROGRESS:\s*(\d+)/(\d+)", line)
        if progress_match:
            progress["active"] = True
            progress["done"] = int(progress_match.group(1))
            progress["total"] = int(progress_match.group(2))
        chunk_match = re.search(r"(REVIEW|REVISE) CHUNK:\s*(.+)", line)
        if chunk_match:
            progress["active"] = True
            progress["label"] = line
    if progress["total"]:
        progress["percent"] = min(100, round(progress["done"] / progress["total"] * 100))
    return progress


def parse_ppt_progress(output):
    progress = {"active": False, "done": 0, "total": 0, "percent": 0, "label": ""}
    for line in output:
        total_match = re.search(r"PPT TOTAL:\s*(\d+)", line)
        if total_match:
            progress["active"] = True
            progress["total"] = int(total_match.group(1))
        progress_match = re.search(r"PPT (?:PROGRESS|IMAGE):\s*(\d+)/(\d+)\s*(.*)", line)
        if progress_match:
            progress["active"] = True
            progress["done"] = int(progress_match.group(1))
            progress["total"] = int(progress_match.group(2))
            progress["label"] = progress_match.group(3).strip()
    if progress["total"]:
        progress["percent"] = min(100, round(progress["done"] / progress["total"] * 100))
    return progress


def ppt_payload(runner):
    plan = {}
    if PPT_PLAN_FILE.exists():
        try:
            plan = json.loads(PPT_PLAN_FILE.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            plan = {}
    sources = list_ppt_sources()
    templates = list_ppt_templates()
    return {
        "progress": parse_ppt_progress(runner.get("output", [])),
        "outline": read_text_file(PPT_OUTLINE_FILE),
        "preview": read_text_file(PPT_PREVIEW_FILE),
        "plan": plan,
        "sources": sources,
        "templates": templates,
        "output": OUTPUT_PPTX.exists(),
    }


def read_project_title():
    config_path = WORK / "configs" / "default.yaml"
    if not config_path.exists():
        return "论文工作流"
    for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"')
    return "论文工作流"


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


def save_local_config(config):
    LOCAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CONFIG_FILE.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_settings():
    config = load_config()
    generation = config.get("engines", {}).get("generation", {})
    provider = generation.get("providers", {}).get("writer", {})
    batch = generation.get("batch", {})
    image_slide = config.get("ppt", {}).get("image_slide", {})
    assembly = config.get("assembly", {})
    references = config.get("references", {})
    target_word_count = int(assembly.get("target_word_count") or assembly.get("min_word_count") or 25000)
    cn_refs = int(references.get("cn_count") or 10)
    en_refs = int(references.get("en_count") or 10)
    return {
        "title": config.get("project", {}).get("title", ""),
        "api_base": provider.get("api_base", ""),
        "api_key": provider.get("api_key", ""),
        "model": provider.get("model", ""),
        "ppt_image_api_base": image_slide.get("api_base", ""),
        "ppt_image_api_key": image_slide.get("api_key", ""),
        "ppt_image_model": image_slide.get("model", ""),
        "ppt_image_size": image_slide.get("size", "1536x1024"),
        "granularity": generation.get("granularity", "chapter"),
        "sleep_seconds": batch.get("sleep_seconds", 3),
        "request_timeout_seconds": batch.get("request_timeout_seconds", 300),
        "max_sections_per_run": batch.get("max_sections_per_run", 0),
        "target_word_count": target_word_count,
        "reference_cn_count": cn_refs,
        "reference_en_count": en_refs,
    }


def update_settings(values):
    config = load_config()
    project = config.setdefault("project", {})
    generation = config.setdefault("engines", {}).setdefault("generation", {})
    providers = generation.setdefault("providers", {})
    provider = providers.setdefault("writer", {})
    batch = generation.setdefault("batch", {})
    image_slide = config.setdefault("ppt", {}).setdefault("image_slide", {})
    assembly = config.setdefault("assembly", {})
    references = config.setdefault("references", {})

    project["title"] = values.get("title", [""])[0].strip()
    provider["api_base"] = values.get("api_base", [""])[0].strip()
    provider["api_key"] = values.get("api_key", [""])[0].strip()
    provider["model"] = values.get("model", [""])[0].strip()
    image_slide["api_base"] = values.get("ppt_image_api_base", [""])[0].strip()
    image_slide["api_key"] = values.get("ppt_image_api_key", [""])[0].strip()
    image_slide["model"] = values.get("ppt_image_model", [""])[0].strip()
    image_slide["size"] = values.get("ppt_image_size", ["1536x1024"])[0].strip() or "1536x1024"
    granularity = values.get("granularity", ["chapter"])[0]
    generation["granularity"] = granularity if granularity in {"chapter", "subsection"} else "chapter"
    batch["sleep_seconds"] = as_number(values.get("sleep_seconds", ["3"])[0], float, 3)
    batch["request_timeout_seconds"] = as_number(values.get("request_timeout_seconds", ["300"])[0], int, 300)
    batch["max_sections_per_run"] = as_number(values.get("max_sections_per_run", ["0"])[0], int, 0)
    target_words = clamp_int(as_number(values.get("target_word_count", ["25000"])[0], int, 25000), 8000, 80000)
    cn_refs = clamp_int(as_number(values.get("reference_cn_count", ["10"])[0], int, 10), 0, 80)
    en_refs = clamp_int(as_number(values.get("reference_en_count", ["10"])[0], int, 10), 0, 80)
    assembly["target_word_count"] = target_words
    assembly["min_word_count"] = min(target_words, max(1, int(target_words * 0.92)))
    references["cn_count"] = cn_refs
    references["en_count"] = en_refs
    references["max_items"] = cn_refs + en_refs
    references["source_policy"] = "google_scholar_or_cnki_queryable"
    save_local_config(config)


def update_settings_json(values):
    config = load_config()
    project = config.setdefault("project", {})
    generation = config.setdefault("engines", {}).setdefault("generation", {})
    providers = generation.setdefault("providers", {})
    provider = providers.setdefault("writer", {})
    batch = generation.setdefault("batch", {})
    image_slide = config.setdefault("ppt", {}).setdefault("image_slide", {})
    assembly = config.setdefault("assembly", {})
    references = config.setdefault("references", {})

    project["title"] = str(values.get("title", "")).strip()
    provider["api_base"] = str(values.get("api_base", "")).strip()
    provider["api_key"] = str(values.get("api_key", "")).strip()
    provider["model"] = str(values.get("model", "")).strip()
    image_slide["api_base"] = str(values.get("ppt_image_api_base", "")).strip()
    image_slide["api_key"] = str(values.get("ppt_image_api_key", "")).strip()
    image_slide["model"] = str(values.get("ppt_image_model", "")).strip()
    image_slide["size"] = str(values.get("ppt_image_size", "1536x1024")).strip() or "1536x1024"
    granularity = str(values.get("granularity", "chapter"))
    generation["granularity"] = granularity if granularity in {"chapter", "subsection"} else "chapter"
    batch["sleep_seconds"] = as_number(values.get("sleep_seconds", 3), float, 3)
    batch["request_timeout_seconds"] = as_number(values.get("request_timeout_seconds", 300), int, 300)
    batch["max_sections_per_run"] = as_number(values.get("max_sections_per_run", 0), int, 0)
    target_words = clamp_int(as_number(values.get("target_word_count", 25000), int, 25000), 8000, 80000)
    cn_refs = clamp_int(as_number(values.get("reference_cn_count", 10), int, 10), 0, 80)
    en_refs = clamp_int(as_number(values.get("reference_en_count", 10), int, 10), 0, 80)
    assembly["target_word_count"] = target_words
    assembly["min_word_count"] = min(target_words, max(1, int(target_words * 0.92)))
    references["cn_count"] = cn_refs
    references["en_count"] = en_refs
    references["max_items"] = cn_refs + en_refs
    references["source_policy"] = "google_scholar_or_cnki_queryable"
    save_local_config(config)


def as_number(value, caster, default):
    try:
        return caster(value)
    except (TypeError, ValueError):
        return default


def clamp_int(value, minimum, maximum):
    return max(minimum, min(maximum, int(value)))


def update_style(values):
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STYLE_FILE.write_text(values.get("style", [""])[0], encoding="utf-8")


def update_style_text(text):
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STYLE_FILE.write_text(text, encoding="utf-8")


def save_style_upload(content_type, body):
    marker = "boundary="
    if marker not in content_type:
        return {"saved": False, "message": "没有收到可导入的写作规范文件。"}
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    delimiter = b"--" + boundary
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    for part in body.split(delimiter):
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        _, _, content = part.partition(b"\r\n\r\n")
        if not content:
            continue
        content = content.rstrip(b"\r\n")
        if content.endswith(b"--"):
            content = content[:-2].rstrip(b"\r\n")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("utf-8", errors="replace")
        STYLE_FILE.write_text(text.strip() + "\n", encoding="utf-8")
        return {"saved": True, "message": "已导入写作规范到 thesis/style.md。"}
    return {"saved": False, "message": "没有选择写作规范文件，未导入。"}


def list_user_files():
    if not USER_DATA_DIR.exists():
        return {"items": [], "total": 0, "total_size": 0, "hidden": 0}
    files = []
    total_size = 0
    for path in sorted(USER_DATA_DIR.rglob("*")):
        if path.is_dir():
            continue
        size = path.stat().st_size
        total_size += size
        files.append(
            {
                "path": path.relative_to(USER_DATA_DIR).as_posix(),
                "size": size,
            }
        )
    return {
        "items": files[:USER_FILE_PREVIEW_LIMIT],
        "total": len(files),
        "total_size": total_size,
        "hidden": max(0, len(files) - USER_FILE_PREVIEW_LIMIT),
    }


def list_ppt_sources():
    if not PPT_SOURCE_DIR.exists():
        return []
    items = []
    for path in sorted(PPT_SOURCE_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix.lower() in {".md", ".markdown", ".txt", ".docx", ".pdf"}:
            items.append({"name": path.name, "path": str(path.relative_to(WORK)), "size": path.stat().st_size})
    return items[:10]


def list_ppt_templates():
    if not PPT_TEMPLATE_DIR.exists():
        return []
    items = []
    for path in sorted(PPT_TEMPLATE_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix.lower() in {".ppt", ".pptx"}:
            items.append({"name": path.name, "path": str(path.relative_to(WORK)), "size": path.stat().st_size})
    return items[:10]


def read_text_file(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def list_downloads():
    items = []
    candidates = [
        ("thesis.md", OUTPUT_MD),
        ("thesis.docx", OUTPUT_DOCX),
        ("thesis_presentation.pptx", OUTPUT_PPTX),
        ("review_results.md", REVIEW_REPORT),
        ("quality_gate_report.md", WORK / "output" / "quality_gate_report.md"),
        ("extraction_report.md", USER_DATA_DIR / "extraction_report.md"),
    ]
    for name, path in candidates:
        if path.exists():
            items.append({"name": name, "url": f"/download/{name}", "size": path.stat().st_size})
    if OUTPUT_DIR.exists():
        items.append({"name": "output.zip", "url": "/download/output.zip", "size": directory_size(OUTPUT_DIR)})
    return items


def directory_size(path):
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def thesis_logs():
    log_dir = WORK / "thesis" / "logs"
    if not log_dir.exists():
        return []
    logs = []
    for path in sorted(log_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
        logs.append({"name": path.name, "size": path.stat().st_size, "mtime": path.stat().st_mtime})
    return logs[:20]


def latest_log_text():
    logs = thesis_logs()
    if not logs:
        return ""
    return read_text_file(WORK / "thesis" / "logs" / logs[0]["name"])[-60000:]


def photo_files():
    if not PHOTO_DIR.exists():
        return []
    return sorted(path for path in PHOTO_DIR.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})


def live_preview():
    rows = load_plan()
    parts = []
    current_chapter = None
    for item in rows:
        relative = item.get("file")
        if not relative:
            continue
        path = WORK / "thesis" / relative
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8-sig", errors="ignore").strip()
        if not content:
            continue
        chapter_title = item.get("chapter_title")
        subsection_title = item.get("subsection_title")
        if subsection_title and chapter_title and chapter_title != current_chapter:
            parts.append(f"# {chapter_title}")
            current_chapter = chapter_title
        parts.append(content)

    if not parts and OUTPUT_MD.exists():
        parts.append(OUTPUT_MD.read_text(encoding="utf-8-sig", errors="ignore"))
    return "\n\n".join(parts)[-PREVIEW_LIMIT:]


def render_markdown(markdown):
    blocks = []
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                blocks.append("</ul>")
                in_list = False
            continue
        if line.startswith("#"):
            if in_list:
                blocks.append("</ul>")
                in_list = False
            level = min(len(line) - len(line.lstrip("#")), 4)
            text = line[level:].strip()
            blocks.append(f"<h{level}>{html.escape(text)}</h{level}>")
        elif line.startswith(("- ", "* ")):
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append(f"<li>{html.escape(line[2:].strip())}</li>")
        else:
            if in_list:
                blocks.append("</ul>")
                in_list = False
            blocks.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        blocks.append("</ul>")
    return "\n".join(blocks) or '<p class="muted">暂无已生成正文。开始生成后会在这里实时出现。</p>'


def save_upload(content_type, body):
    marker = "boundary="
    if marker not in content_type:
        return {"saved": 0, "skipped": 0, "message": "没有收到文件或文件夹。"}
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    delimiter = b"--" + boundary
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    skipped = 0
    for part in body.split(delimiter):
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        header, _, content = part.partition(b"\r\n\r\n")
        if not content:
            continue
        filename = multipart_filename(header)
        if not filename:
            skipped += 1
            continue
        safe_path = safe_relative_upload_path(filename)
        if safe_path is None:
            skipped += 1
            continue
        content = content.rstrip(b"\r\n")
        if content.endswith(b"--"):
            content = content[:-2].rstrip(b"\r\n")
        target = USER_DATA_DIR / safe_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        saved += 1
    if saved:
        summary = list_user_files()
        return {
            "saved": saved,
            "skipped": skipped,
            "message": f"已导入 {saved} 个文件；当前 user_data 共 {summary['total']} 个文件。",
        }
    return {"saved": 0, "skipped": skipped, "message": "没有选择文件或文件夹，未导入。"}


def save_ppt_upload(content_type, body):
    marker = "boundary="
    if marker not in content_type:
        return {"saved": 0, "message": "没有收到 PPT 论文源文件。"}
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    delimiter = b"--" + boundary
    PPT_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    allowed = {".md", ".markdown", ".txt", ".docx", ".pdf"}
    for part in body.split(delimiter):
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        header, _, content = part.partition(b"\r\n\r\n")
        filename = multipart_filename(header)
        if not filename:
            continue
        safe_path = safe_relative_upload_path(Path(filename).name)
        if safe_path is None:
            continue
        target = PPT_SOURCE_DIR / safe_path.name
        if target.suffix.lower() not in allowed:
            continue
        content = content.rstrip(b"\r\n")
        if content.endswith(b"--"):
            content = content[:-2].rstrip(b"\r\n")
        target.write_bytes(content)
        saved.append(target)
    if not saved:
        return {"saved": 0, "message": "请选择 md、docx、pdf 或 txt 论文文件。"}
    latest = saved[-1].relative_to(WORK).as_posix()
    return {"saved": len(saved), "source": latest, "message": f"已导入 {len(saved)} 个 PPT 论文源文件。"}


def save_ppt_template_upload(content_type, body):
    marker = "boundary="
    if marker not in content_type:
        return {"saved": 0, "message": "没有收到参考 PPT 文件。"}
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    delimiter = b"--" + boundary
    PPT_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    allowed = {".ppt", ".pptx"}
    for part in body.split(delimiter):
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        header, _, content = part.partition(b"\r\n\r\n")
        filename = multipart_filename(header)
        if not filename:
            continue
        safe_path = safe_relative_upload_path(Path(filename).name)
        if safe_path is None:
            continue
        target = PPT_TEMPLATE_DIR / safe_path.name
        if target.suffix.lower() not in allowed:
            continue
        content = content.rstrip(b"\r\n")
        if content.endswith(b"--"):
            content = content[:-2].rstrip(b"\r\n")
        target.write_bytes(content)
        saved.append(target)
    if not saved:
        return {"saved": 0, "message": "请选择 ppt 或 pptx 参考 PPT 文件。"}
    latest = saved[-1].relative_to(WORK).as_posix()
    return {"saved": len(saved), "template": latest, "message": f"已导入 {len(saved)} 个参考 PPT。生成时只分析布局、色彩和母版结构，不复用文字与图片内容。"}


def multipart_filename(header):
    """Extract only the Content-Disposition filename from a multipart part header."""
    text = header.decode("utf-8", errors="replace")
    disposition = ""
    for line in text.splitlines():
        if line.lower().startswith("content-disposition:"):
            disposition = line
            break
    if not disposition:
        return ""
    encoded = re.search(r"filename\*=(?:UTF-8''|utf-8'')?([^;]+)", disposition)
    if encoded:
        return unquote(encoded.group(1).strip().strip('"'))
    quoted = re.search(r'filename="([^"]*)"', disposition)
    if quoted:
        return quoted.group(1)
    plain = re.search(r"filename=([^;]+)", disposition)
    return plain.group(1).strip().strip('"') if plain else ""


def safe_relative_upload_path(filename):
    parts = []
    for part in filename.replace("\\", "/").split("/"):
        cleaned = re.sub(r'[\x00-\x1f<>:"|?*]', "_", part).strip().strip(".")
        if not cleaned or cleaned in {".", ".."}:
            continue
        parts.append(cleaned)
    if not parts:
        return None
    return Path(*parts)


def run_command(name):
    commands = {
        "all": [sys.executable, "workflow.py", "all"],
        "generate": [sys.executable, "workflow.py", "generate", "--all"],
        "style": [sys.executable, "workflow.py", "style", "--overwrite"],
        "resources": [sys.executable, "workflow.py", "resources", "--overwrite"],
        "references": [sys.executable, "workflow.py", "references", "--overwrite"],
        "outline": [sys.executable, "workflow.py", "outline", "--overwrite"],
        "plan": [sys.executable, "workflow.py", "plan", "--overwrite-state"],
        "build": [sys.executable, "workflow.py", "build"],
        "ppt": [sys.executable, "workflow.py", "ppt"],
        "review": [sys.executable, "workflow.py", "review"],
        "reset": [sys.executable, "workflow.py", "reset", "--yes"],
    }
    messages = {
        "review": "Review 已启动：会按章节/分块串行检测，生成 review 报告和日志，完成后重新构建 thesis.docx。",
        "reset": "重置已启动：会清空 user_data、已生成章节、输出文件和日志，保留 API 配置。",
        "references": "参考文献生成已启动：会优先读取 BibTeX，没有 BibTeX 时尝试联网检索并生成 references.bib / references.md。",
        "ppt": "PPT 生成已启动：会根据 output/thesis.md 生成 output/thesis_presentation.pptx。",
    }
    if name not in commands:
        return False, "未知命令"
    ok, message = RUNNER.start(commands[name])
    return ok, messages.get(name, message) if ok else message


def run_ppt_command(style="infographic", source="", template="", render_mode="editable"):
    style = style if style in {"infographic", "excalidraw", "architecture"} else "infographic"
    render_mode = render_mode if render_mode in {"editable", "image_slide"} else "editable"
    command = [sys.executable, "workflow.py", "ppt", "--style", style]
    command.extend(["--render-mode", render_mode])
    if source:
        source_path = (WORK / source).resolve()
        try:
            source_path.relative_to(WORK.resolve())
        except ValueError:
            return False, "PPT 输入文件必须位于项目目录内。"
        if not source_path.exists():
            return False, "PPT 输入文件不存在。"
        command.extend(["--input", str(source_path)])
    if template:
        if template == "__all__":
            template_paths = [Path(item["path"]) for item in list_ppt_templates()]
            if not template_paths:
                return False, "还没有导入参考 PPT。"
        else:
            template_paths = [Path(template)]
        for item in template_paths:
            template_path = (WORK / item).resolve()
            try:
                template_path.relative_to(WORK.resolve())
            except ValueError:
                return False, "参考 PPT 文件必须位于项目目录内。"
            if not template_path.exists():
                return False, "参考 PPT 文件不存在。"
            command.extend(["--template", str(template_path)])
    ok, message = RUNNER.start(command)
    if not ok:
        return ok, message
    source_label = source or "output/thesis.md"
    template_label = "全部参考 PPT" if template == "__all__" else (template or "默认设计")
    mode_label = "整页图片" if render_mode == "image_slide" else "可编辑"
    return True, f"PPT 生成已启动：输入 {source_label}，参考设计 {template_label}，风格 {style}，模式 {mode_label}。"


def frontend_sources_newer_than_dist():
    index = FRONTEND_DIST / "index.html"
    source_root = WORK / "workflows" / "webui" / "frontend" / "src"
    if not index.exists() or not source_root.exists():
        return False
    dist_mtime = index.stat().st_mtime
    watched = [WORK / "workflows" / "webui" / "frontend" / "package.json"]
    watched.extend(path for path in source_root.rglob("*") if path.is_file())
    return any(path.stat().st_mtime > dist_mtime for path in watched if path.exists())


def set_pause(paused):
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if paused:
        PAUSE_FILE.write_text("paused\n", encoding="utf-8")
    elif PAUSE_FILE.exists():
        PAUSE_FILE.unlink()


def render_page(notice=""):
    data = status_payload()
    percent = 0 if not data["total"] else round(data["done"] * 100 / data["total"])
    current = data["current"] or {}
    runner = data["runner"]
    rows = "\n".join(
        f"""<tr>
          <td><span class="status {html.escape(item.get('status', 'pending'))}">{html.escape(item.get('status', 'pending'))}</span></td>
          <td>{html.escape(item.get('id', ''))}</td>
          <td>{html.escape(item.get('chapter_title') or item.get('title', ''))}</td>
          <td>{html.escape(item.get('subsection_title') or item.get('title', ''))}</td>
          <td>{html.escape(item.get('file', ''))}</td>
        </tr>"""
        for item in data["sections"]
    )
    logs = "\n".join(html.escape(line) for line in runner["output"])
    running_text = "运行中" if runner["running"] else "空闲"
    paused_text = "已请求暂停" if data["paused"] else "未暂停"
    settings = data["config"]
    chapter_selected = "selected" if settings.get("granularity") == "chapter" else ""
    subsection_selected = "selected" if settings.get("granularity") == "subsection" else ""
    file_summary = data["user_files"]
    user_files = "\n".join(
        f"<tr><td>{html.escape(item['path'])}</td><td>{item['size']}</td></tr>" for item in file_summary["items"]
    )
    photos = photo_files()
    hero_photo = f"/photo/{html.escape(photos[0].name)}" if photos else ""
    preview_html = render_markdown(data["preview"])
    download_links = " ".join(
        f'<a class="download-link" href="{html.escape(item["url"])}">{html.escape(item["name"])}</a>'
        for item in data.get("downloads", [])
    )
    latest_log = html.escape(data.get("latest_log", "") or "暂无日志内容")
    stale_frontend_warning = (
        '<div class="notice">React WebUI 构建产物已过期。请运行 '
        '<code>cd workflows/webui/frontend && npm run build</code> 后重启 WebUI。</div>'
        if frontend_sources_newer_than_dist()
        else ""
    )
    outline_html = (
        render_markdown(data["outline"])
        if data["outline"]
        else '<p class="muted">暂无大纲。点击“重建大纲”后会在这里显示。</p>'
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIGC Thesis Toolkit</title>
  <style>
    :root {{ color-scheme: light; font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }}
    body {{ margin: 0; color: #273043; background: #fff7fb; background-image: linear-gradient(135deg, rgba(255,126,185,.18), rgba(109,213,237,.18) 45%, rgba(255,230,109,.20)); }}
    header {{ position: relative; min-height: 230px; color: white; overflow: hidden; background: #273043; }}
    header::before {{ content: ""; position: absolute; inset: 0; background: linear-gradient(90deg, rgba(36,28,64,.88), rgba(36,28,64,.45), rgba(36,28,64,.15)), url('{hero_photo}'); background-size: cover; background-position: center; }}
    header .hero {{ position: relative; z-index: 1; max-width: 1180px; margin: 0 auto; padding: 34px 24px; }}
    main {{ max-width: 1320px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0; font-size: 30px; font-weight: 800; text-shadow: 0 2px 12px rgba(0,0,0,.35); }}
    h2 {{ font-size: 17px; margin: 26px 0 12px; color: #523f7d; }}
    h3 {{ font-size: 14px; margin: 0 0 10px; color: #6f4aa8; }}
    .subtitle {{ margin-top: 10px; max-width: 760px; color: #f8eafa; line-height: 1.65; }}
    .bar {{ height: 14px; background: rgba(255,255,255,.65); border-radius: 999px; overflow: hidden; box-shadow: inset 0 0 0 1px rgba(124,91,169,.18); }}
    .bar span {{ display: block; height: 100%; width: {percent}%; background: linear-gradient(90deg, #ff7eb9, #7afcff, #ffe66d); }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }}
    .workspace {{ display: grid; grid-template-columns: minmax(360px, .95fr) minmax(480px, 1.35fr); gap: 18px; align-items: start; margin-top: 20px; }}
    .stack {{ display: grid; gap: 16px; }}
    .panel {{ background: rgba(255,255,255,.88); border: 1px solid rgba(155,126,205,.32); border-radius: 12px; padding: 14px; box-shadow: 0 10px 30px rgba(87,64,133,.10); backdrop-filter: blur(8px); }}
    .label {{ color: #7c6a99; font-size: 12px; }}
    .value {{ margin-top: 6px; font-size: 18px; font-weight: 700; overflow-wrap: anywhere; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .formgrid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    label {{ display: block; font-size: 12px; color: #526579; margin-bottom: 5px; }}
    input, select, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #cab8ee; border-radius: 9px; padding: 9px; font: inherit; background: rgba(255,255,255,.92); }}
    textarea {{ min-height: 210px; resize: vertical; }}
    button {{ border: 1px solid #c7abea; background: rgba(255,255,255,.95); color: #3d315b; border-radius: 999px; padding: 9px 14px; cursor: pointer; font-weight: 700; box-shadow: 0 5px 14px rgba(111,74,168,.12); }}
    button:hover {{ transform: translateY(-1px); }}
    button.primary {{ background: linear-gradient(135deg, #ff7eb9, #7b61ff); color: white; border-color: transparent; }}
    button.warn {{ background: linear-gradient(135deg, #ffd166, #ff9f6e); border-color: transparent; color: #3d315b; }}
    button.good {{ background: linear-gradient(135deg, #45d483, #4cc9f0); border-color: transparent; color: white; }}
    button.danger {{ background: linear-gradient(135deg, #ff5f6d, #ffc371); border-color: transparent; color: white; }}
    table {{ width: 100%; border-collapse: collapse; background: rgba(255,255,255,.88); border: 1px solid rgba(155,126,205,.28); }}
    th, td {{ text-align: left; border-bottom: 1px solid rgba(155,126,205,.18); padding: 8px; font-size: 13px; vertical-align: top; }}
    th {{ background: #f3eaff; color: #523f7d; }}
    .status {{ display: inline-block; min-width: 78px; text-align: center; border-radius: 999px; padding: 2px 8px; font-size: 12px; background: #d9e2ec; }}
    .done {{ background: #d4f4dd; color: #176b35; }}
    .in_progress {{ background: #fff0c2; color: #7a4d00; }}
    pre {{ background: #241c40; color: #f5eaff; padding: 14px; border-radius: 12px; max-height: 360px; overflow: auto; font-size: 12px; }}
    .preview {{ max-height: 560px; overflow: auto; line-height: 1.78; background: rgba(255,255,255,.92); }}
    .preview h1 {{ color: #4f378b; text-shadow: none; font-size: 24px; border-bottom: 2px solid #ffd1e8; padding-bottom: 8px; }}
    .preview h2 {{ color: #ad4f92; margin-top: 18px; }}
    .preview h3, .preview h4 {{ color: #3d8fb8; }}
    .preview p {{ margin: 8px 0; }}
    .muted {{ color: #826f9f; }}
    .toolbar-note {{ color: #6b5a84; margin: -8px 0 14px; font-size: 13px; }}
    .notice {{ margin: 18px 0 0; border: 1px solid rgba(87,184,123,.35); background: rgba(226,255,235,.86); color: #24543a; border-radius: 12px; padding: 11px 14px; font-weight: 700; }}
    .upload-zone {{ border: 2px dashed #d59bea; border-radius: 16px; padding: 18px; background: linear-gradient(135deg, rgba(255,255,255,.9), rgba(255,232,246,.75)); }}
    .examples {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; color: #5f4f79; font-size: 13px; }}
    .example {{ background: rgba(255,255,255,.7); border: 1px solid rgba(155,126,205,.22); border-radius: 10px; padding: 8px; }}
    .download-link {{ display: inline-block; margin: 5px 8px 5px 0; padding: 7px 10px; border-radius: 999px; border: 1px solid rgba(155,126,205,.28); color: #523f7d; background: rgba(255,255,255,.78); text-decoration: none; font-weight: 700; }}
    @media (max-width: 760px) {{ .grid {{ grid-template-columns: 1fr; }} main {{ padding: 14px; }} }}
    @media (max-width: 980px) {{ .formgrid, .workspace {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header><div class="hero"><h1>AIGC Thesis Toolkit</h1><div class="subtitle">{html.escape(data["project"] if data["project"] != "你的论文题目" else "本地论文写作工作台")}<br>上传资料、配置模型、连续生成论文，并实时预览已写出的正文。关闭页面不会停止后台任务，使用“关闭 WebUI”或终端 Ctrl+C 结束服务。</div></div></header>
  <main>
    <div class="bar" title="{percent}%"><span></span></div>
    <div class="grid">
      <div class="panel"><div class="label">进度</div><div class="value" id="metric-progress">{data["done"]}/{data["total"]} 写作单元</div></div>
      <div class="panel"><div class="label">任务</div><div class="value" id="metric-running">{running_text}</div></div>
      <div class="panel"><div class="label">暂停</div><div class="value" id="metric-paused">{paused_text}</div></div>
      <div class="panel"><div class="label">当前写作单元</div><div class="value" id="metric-current">{html.escape(current.get("subsection_title") or current.get("title") or "无")}</div></div>
    </div>

    <form class="actions" method="post" action="/action">
      <button class="primary" name="cmd" value="all">开始完整流程</button>
      <button name="cmd" value="generate">继续生成正文</button>
      <button class="warn" name="cmd" value="pause">暂停</button>
      <button class="good" name="cmd" value="resume">继续</button>
      <button name="cmd" value="style">自动生成规范</button>
      <button name="cmd" value="resources">刷新资料索引</button>
      <button name="cmd" value="references">生成参考文献</button>
      <button name="cmd" value="outline">重建大纲</button>
      <button name="cmd" value="plan">重建写作计划</button>
      <button name="cmd" value="build">构建 Word</button>
      <button name="cmd" value="review">论文 Review</button>
      <button class="danger" name="cmd" value="reset" onclick="return confirm('确认清空 user_data、生成章节、输出文件和日志？API 配置会保留。')">一键重置</button>
      <button class="danger" name="cmd" value="shutdown">关闭 WebUI</button>
    </form>
    <div class="toolbar-note">打开：终端运行 <code>python workflow.py ui</code>。关闭：点“关闭 WebUI”，或在运行它的终端按 Ctrl+C。旧后台服务可用 <code>pkill -f workflows/webui/server.py</code> 结束。</div>
    {f'<div class="notice">{html.escape(notice)}</div>' if notice else ''}
    {stale_frontend_warning}

    <section class="workspace">
      <div class="stack">
        <section>
          <h2>项目配置</h2>
          <form class="panel" method="post" action="/settings">
            <div class="formgrid">
              <div><label>论文题目</label><input name="title" value="{html.escape(str(settings['title']))}"></div>
              <div><label>API Base</label><input name="api_base" value="{html.escape(str(settings['api_base']))}"></div>
              <div><label>模型</label><input name="model" value="{html.escape(str(settings['model']))}"></div>
              <div><label>API Key，保存到 configs/local.yaml，不提交 GitHub</label><input name="api_key" type="password" value="{html.escape(str(settings['api_key']))}"></div>
              <div><label>生成粒度</label><select name="granularity"><option value="chapter" {chapter_selected}>按章高质量生成</option><option value="subsection" {subsection_selected}>按小节省 token 生成</option></select></div>
              <div><label>写作单元间隔秒数</label><input name="sleep_seconds" value="{html.escape(str(settings['sleep_seconds']))}"></div>
              <div><label>请求超时秒数</label><input name="request_timeout_seconds" value="{html.escape(str(settings['request_timeout_seconds']))}"></div>
              <div><label>本轮最多写作单元数，0 为不限制</label><input name="max_sections_per_run" value="{html.escape(str(settings['max_sections_per_run']))}"></div>
            </div>
            <div class="actions"><button class="primary">保存配置</button></div>
          </form>
        </section>

        <section>
          <h2>资料文件</h2>
          <form class="panel upload-zone" method="post" action="/upload" enctype="multipart/form-data" onsubmit="return hasSelectedFiles(this);">
            <h3>上传到 user_data</h3>
            <div class="muted">建议上传与论文直接相关的资料，系统会尽量抽取 DOC、DOCX、PDF、图片 OCR、BibTeX 和表格内容，再生成资料索引。</div>
            <div class="examples">
              <div class="example">开题报告、中期报告、任务书</div>
              <div class="example">参考论文、BibTeX、文献笔记</div>
              <div class="example">仿真数据、实验数据、表格</div>
              <div class="example">原理图、流程图、实物照片</div>
            </div>
            <p><label>选择零散文件</label><input type="file" name="files" multiple></p>
            <p><label>选择整个文件夹</label><input type="file" name="files" webkitdirectory directory multiple></p>
            <div class="muted">两个入口共用同一个“上传文件”按钮；可以一次性导入多文件，也可以一次性导入一个文件夹。</div>
            <div class="actions"><button class="primary">上传文件</button></div>
          </form>
          <div class="panel">
            <h3>已有资料</h3>
            <div class="muted">共 {file_summary['total']} 个文件，约 {file_summary['total_size']} bytes。这里只显示前 {USER_FILE_PREVIEW_LIMIT} 个，避免大文件夹刷屏。</div>
            <table>
              <thead><tr><th>文件</th><th>大小 bytes</th></tr></thead>
              <tbody>{user_files or '<tr><td colspan="2">尚未上传资料</td></tr>'}</tbody>
            </table>
            {f'<div class="muted">还有 {file_summary["hidden"]} 个文件未在列表中展开显示。</div>' if file_summary["hidden"] else ''}
          </div>
        </section>

        <section>
          <h2>写作规范</h2>
          <form class="panel" method="post" action="/style">
            <textarea name="style">{html.escape(data["style"])}</textarea>
            <div class="actions"><button class="primary">保存写作规范</button></div>
          </form>
          <form class="panel" method="post" action="/style-upload" enctype="multipart/form-data">
            <h3>导入写作规范</h3>
            <div class="muted">支持上传 Markdown/TXT 格式的学校论文规范、格式说明或你整理好的 style.md。PDF/Word 请先转成文本，或放入 user_data 后点击“自动生成规范”。</div>
            <p><input type="file" name="style_file" required></p>
            <div class="actions"><button class="primary">导入为 thesis/style.md</button></div>
          </form>
        </section>
      </div>

      <div class="stack">
        <section>
          <h2>论文大纲</h2>
          <article class="panel preview outline-preview" id="outline">{outline_html}</article>
        </section>
        <section>
          <h2>实时论文预览</h2>
          <article class="panel preview" id="preview">{preview_html}</article>
        </section>
        <section>
          <h2>任务输出</h2>
          <pre id="logs">{logs or "暂无输出"}</pre>
        </section>
        <section>
          <h2>导出与反思日志</h2>
          <div class="panel">{download_links or '<span class="muted">暂无可下载文件，请先构建 Word 或运行 Review。</span>'}</div>
          <pre id="latest-log">{latest_log}</pre>
        </section>
      </div>
    </section>

    <h2>写作计划</h2>
    <table>
      <thead><tr><th>状态</th><th>ID</th><th>章</th><th>小节</th><th>文件</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="5">尚未生成计划</td></tr>'}</tbody>
    </table>
  </main>
  <script>
    function hasSelectedFiles(form) {{
      for (const input of form.querySelectorAll('input[type="file"]')) {{
        if (input.files && input.files.length > 0) return true;
      }}
      alert('请先选择文件或文件夹。');
      return false;
    }}

    function renderMarkdown(text) {{
      if (!text) return '<p class="muted">暂无已生成正文。开始生成后会在这里实时出现。</p>';
      const escapeHtml = value => value.replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
      let html = '';
      let inList = false;
      for (const raw of text.split(/\\r?\\n/)) {{
        const line = raw.trim();
        if (!line) {{
          if (inList) {{ html += '</ul>'; inList = false; }}
          continue;
        }}
        if (line.startsWith('#')) {{
          if (inList) {{ html += '</ul>'; inList = false; }}
          const level = Math.min((line.match(/^#+/) || [''])[0].length, 4);
          html += `<h${{level}}>${{escapeHtml(line.slice(level).trim())}}</h${{level}}>`;
        }} else if (line.startsWith('- ') || line.startsWith('* ')) {{
          if (!inList) {{ html += '<ul>'; inList = true; }}
          html += `<li>${{escapeHtml(line.slice(2).trim())}}</li>`;
        }} else {{
          if (inList) {{ html += '</ul>'; inList = false; }}
          html += `<p>${{escapeHtml(line)}}</p>`;
        }}
      }}
      if (inList) html += '</ul>';
      return html;
    }}

    async function refreshStatus() {{
      try {{
        const response = await fetch('/status');
        const data = await response.json();
        const percent = data.total ? Math.round(data.done * 100 / data.total) : 0;
        document.querySelector('.bar span').style.width = percent + '%';
        document.getElementById('metric-progress').textContent = `${{data.done}}/${{data.total}} 写作单元`;
        document.getElementById('metric-running').textContent = data.runner.running ? '运行中' : '空闲';
        document.getElementById('metric-paused').textContent = data.paused ? '已请求暂停' : '未暂停';
        document.getElementById('metric-current').textContent = (data.current && (data.current.subsection_title || data.current.title)) || '无';
        document.getElementById('logs').textContent = data.runner.output.length ? data.runner.output.join('\\n') : '暂无输出';
        document.getElementById('preview').innerHTML = renderMarkdown(data.preview || '');
        document.getElementById('outline').innerHTML = data.outline ? renderMarkdown(data.outline) : '<p class="muted">暂无大纲。点击“重建大纲”后会在这里显示。</p>';
      }} catch (error) {{
        console.warn(error);
      }}
    }}
    setInterval(refreshStatus, 5000);
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            self.send_json(status_payload())
            return
        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return
        if parsed.path.startswith("/photo/"):
            self.send_file(PHOTO_DIR / Path(parsed.path).name)
            return
        if parsed.path.startswith("/download/"):
            self.send_download(Path(parsed.path).name)
            return
        if parsed.path.startswith("/assets/") or parsed.path in {"/", "/index.html"}:
            if not frontend_sources_newer_than_dist() and self.try_send_frontend(parsed.path):
                return
        notice = parse_qs(parsed.query).get("notice", [""])[0]
        self.send_html(render_page(notice=notice))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_post(parsed.path, raw_body)
            return
        notice = ""
        if parsed.path == "/upload":
            notice = save_upload(self.headers.get("Content-Type", ""), raw_body)["message"]
        elif parsed.path == "/style-upload":
            notice = save_style_upload(self.headers.get("Content-Type", ""), raw_body)["message"]
        else:
            body = raw_body.decode("utf-8")
            values = parse_qs(body)
            if parsed.path == "/settings":
                update_settings(values)
                notice = "配置已保存。"
            elif parsed.path == "/style":
                update_style(values)
                notice = "写作规范已保存。"
            else:
                cmd = values.get("cmd", [""])[0]
                if cmd == "pause":
                    set_pause(True)
                    notice = "已请求暂停：当前写作单元完成后会停在下一个写作单元之前。"
                elif cmd == "resume":
                    set_pause(False)
                    notice = "已恢复生成。"
                elif cmd == "shutdown":
                    RUNNER.stop()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write("WebUI 已关闭，可以关闭这个页面。".encode("utf-8"))
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif cmd == "reset":
                    ok, message = run_command(cmd)
                    notice = message
                else:
                    ok, message = run_command(cmd)
                    notice = message
        self.send_response(303)
        self.send_header("Location", f"/?notice={quote(notice)}")
        self.end_headers()

    def handle_api_post(self, path, raw_body):
        notice = ""
        if path == "/api/upload":
            result = save_upload(self.headers.get("Content-Type", ""), raw_body)
            self.send_json({"ok": result["saved"] > 0, **result})
            return
        if path == "/api/style-upload":
            result = save_style_upload(self.headers.get("Content-Type", ""), raw_body)
            self.send_json({"ok": result["saved"], **result})
            return
        if path == "/api/ppt-upload":
            result = save_ppt_upload(self.headers.get("Content-Type", ""), raw_body)
            self.send_json({"ok": result["saved"] > 0, **result, "status": status_payload()})
            return
        if path == "/api/ppt-template-upload":
            result = save_ppt_template_upload(self.headers.get("Content-Type", ""), raw_body)
            self.send_json({"ok": result["saved"] > 0, **result, "status": status_payload()})
            return

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_json({"ok": False, "message": "请求 JSON 格式错误。"}, status=400)
            return

        if path == "/api/settings":
            update_settings_json(payload)
            self.send_json({"ok": True, "message": "配置已保存。", "status": status_payload()})
            return
        if path == "/api/style":
            update_style_text(str(payload.get("style", "")))
            self.send_json({"ok": True, "message": "写作规范已保存。", "status": status_payload()})
            return
        if path == "/api/ppt-generate":
            style = str(payload.get("style", "infographic"))
            source = str(payload.get("source", "") or "")
            template = str(payload.get("template", "") or "")
            render_mode = str(payload.get("render_mode", "editable") or "editable")
            ok, notice = run_ppt_command(style=style, source=source, template=template, render_mode=render_mode)
            self.send_json({"ok": ok, "message": notice, "status": status_payload()})
            return
        if path == "/api/action":
            cmd = str(payload.get("cmd", ""))
            if cmd == "pause":
                set_pause(True)
                notice = "已请求暂停：当前写作单元完成后会停在下一个写作单元之前。"
            elif cmd == "resume":
                set_pause(False)
                notice = "已恢复生成。"
            elif cmd == "shutdown":
                RUNNER.stop()
                self.send_json({"ok": True, "message": "WebUI 已关闭。"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            elif cmd == "reset":
                ok, notice = run_command(cmd)
                self.send_json({"ok": ok, "message": notice, "status": status_payload()})
                return
            else:
                ok, notice = run_command(cmd)
                self.send_json({"ok": ok, "message": notice, "status": status_payload()})
                return
            self.send_json({"ok": True, "message": notice, "status": status_payload()})
            return

        self.send_json({"ok": False, "message": "未知 API。"}, status=404)

    def send_html(self, content):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def try_send_frontend(self, route):
        if not FRONTEND_DIST.exists():
            return False
        path = route
        if path in {"/", "/index.html"}:
            target = FRONTEND_DIST / "index.html"
        else:
            normalized = posixpath.normpath(unquote(path)).lstrip("/")
            target = FRONTEND_DIST / normalized
        try:
            target.resolve().relative_to(FRONTEND_DIST.resolve())
        except ValueError:
            self.send_error(404)
            return True
        if target.exists() and target.is_file():
            self._send_file(target, FRONTEND_DIST)
            return True
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            self._send_file(index, FRONTEND_DIST)
            return True
        return False

    def send_file(self, path):
        self._send_file(path, PHOTO_DIR)

    def _send_file(self, path, root):
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            self.send_error(404)
            return
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_download(self, name):
        mapping = {
            "thesis.md": OUTPUT_MD,
            "thesis.docx": OUTPUT_DOCX,
            "thesis_presentation.pptx": OUTPUT_PPTX,
            "review_results.md": REVIEW_REPORT,
            "quality_gate_report.md": WORK / "output" / "quality_gate_report.md",
            "extraction_report.md": USER_DATA_DIR / "extraction_report.md",
        }
        if name == "output.zip":
            if not OUTPUT_DIR.exists():
                self.send_error(404)
                return
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
                zip_path = Path(handle.name)
            try:
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for file in OUTPUT_DIR.rglob("*"):
                        if file.is_file():
                            archive.write(file, file.relative_to(OUTPUT_DIR).as_posix())
                self.send_attachment(zip_path, "output.zip")
            finally:
                zip_path.unlink(missing_ok=True)
            return

        path = mapping.get(name)
        if path is None or not path.exists():
            self.send_error(404)
            return
        self.send_attachment(path, name)

    def send_attachment(self, path, filename):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
    else:
        raise SystemExit(f"No free port found in {port}-{port + 19}")
    print(f"Web UI: http://127.0.0.1:{candidate}")
    server.serve_forever()


if __name__ == "__main__":
    main()
