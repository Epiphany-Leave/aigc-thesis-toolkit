#!/usr/bin/env python3
"""Small local Web UI for the thesis workflow."""

from __future__ import annotations

import html
import errno
import json
import mimetypes
import subprocess
import sys
import threading
import time
import uuid
import yaml
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


WORK = Path(__file__).resolve().parents[2]
PLAN_FILE = WORK / "thesis" / "section_plan.json"
PAUSE_FILE = WORK / "thesis" / "pause.flag"
OUTPUT_DOCX = WORK / "output" / "thesis.docx"
OUTPUT_MD = WORK / "output" / "thesis.md"
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"
STYLE_FILE = WORK / "thesis" / "style.md"
USER_DATA_DIR = WORK / "user_data"
PHOTO_DIR = WORK / "workflows" / "webui" / "photo"
PREVIEW_LIMIT = 60000


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
            self.process = subprocess.Popen(
                command,
                cwd=WORK,
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


RUNNER = Runner()


def load_plan():
    if not PLAN_FILE.exists():
        return []
    return json.loads(PLAN_FILE.read_text(encoding="utf-8-sig")).get("sections", [])


def status_payload():
    rows = load_plan()
    done = sum(1 for item in rows if item.get("status") == "done")
    current = next((item for item in rows if item.get("status") != "done"), None)
    return {
        "project": read_project_title(),
        "done": done,
        "total": len(rows),
        "current": current,
        "sections": rows,
        "paused": PAUSE_FILE.exists(),
        "output_docx": OUTPUT_DOCX.exists(),
        "output_md": OUTPUT_MD.exists(),
        "runner": RUNNER.snapshot(),
        "config": load_settings(),
        "style": STYLE_FILE.read_text(encoding="utf-8") if STYLE_FILE.exists() else "",
        "user_files": list_user_files(),
        "preview": live_preview(),
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
    config = {}
    generation = config.get("engines", {}).get("generation", {})
    provider = generation.get("providers", {}).get("writer", {})
    batch = generation.get("batch", {})
    return {
        "title": config.get("project", {}).get("title", ""),
        "api_base": provider.get("api_base", ""),
        "api_key": provider.get("api_key", ""),
        "model": provider.get("model", ""),
        "sleep_seconds": batch.get("sleep_seconds", 3),
        "request_timeout_seconds": batch.get("request_timeout_seconds", 180),
        "max_sections_per_run": batch.get("max_sections_per_run", 0),
    }


def update_settings(values):
    config = load_config()
    project = config.setdefault("project", {})
    generation = config.setdefault("engines", {}).setdefault("generation", {})
    providers = generation.setdefault("providers", {})
    provider = providers.setdefault("writer", {})
    batch = generation.setdefault("batch", {})

    project["title"] = values.get("title", [""])[0].strip()
    provider["api_base"] = values.get("api_base", [""])[0].strip()
    provider["api_key"] = values.get("api_key", [""])[0].strip()
    provider["model"] = values.get("model", [""])[0].strip()
    batch["sleep_seconds"] = as_number(values.get("sleep_seconds", ["3"])[0], float, 3)
    batch["request_timeout_seconds"] = as_number(values.get("request_timeout_seconds", ["180"])[0], int, 180)
    batch["max_sections_per_run"] = as_number(values.get("max_sections_per_run", ["0"])[0], int, 0)
    save_local_config(config)


def as_number(value, caster, default):
    try:
        return caster(value)
    except (TypeError, ValueError):
        return default


def update_style(values):
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STYLE_FILE.write_text(values.get("style", [""])[0], encoding="utf-8")


def save_style_upload(content_type, body):
    marker = "boundary="
    if marker not in content_type:
        return
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
        return


def list_user_files():
    if not USER_DATA_DIR.exists():
        return []
    files = []
    for path in sorted(USER_DATA_DIR.rglob("*")):
        if path.is_dir():
            continue
        files.append(
            {
                "path": path.relative_to(USER_DATA_DIR).as_posix(),
                "size": path.stat().st_size,
            }
        )
    return files


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
        return
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    delimiter = b"--" + boundary
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for part in body.split(delimiter):
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        header, _, content = part.partition(b"\r\n\r\n")
        if not content:
            continue
        disposition = header.decode("utf-8", errors="ignore")
        filename = ""
        for segment in disposition.split(";"):
            segment = segment.strip()
            if segment.startswith("filename="):
                filename = segment.split("=", 1)[1].strip().strip('"')
        if not filename:
            continue
        safe_name = Path(filename.replace("\\", "/")).name
        if not safe_name:
            safe_name = f"upload-{uuid.uuid4().hex}"
        content = content.rstrip(b"\r\n")
        if content.endswith(b"--"):
            content = content[:-2].rstrip(b"\r\n")
        (USER_DATA_DIR / safe_name).write_bytes(content)


def run_command(name):
    commands = {
        "all": [sys.executable, "workflow.py", "all"],
        "generate": [sys.executable, "workflow.py", "generate", "--all"],
        "style": [sys.executable, "workflow.py", "style", "--overwrite"],
        "resources": [sys.executable, "workflow.py", "resources", "--overwrite"],
        "outline": [sys.executable, "workflow.py", "outline", "--overwrite"],
        "plan": [sys.executable, "workflow.py", "plan", "--overwrite-state"],
        "build": [sys.executable, "workflow.py", "build"],
    }
    if name not in commands:
        return False, "未知命令"
    return RUNNER.start(commands[name])


def set_pause(paused):
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if paused:
        PAUSE_FILE.write_text("paused\n", encoding="utf-8")
    elif PAUSE_FILE.exists():
        PAUSE_FILE.unlink()


def render_page():
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
    user_files = "\n".join(
        f"<tr><td>{html.escape(item['path'])}</td><td>{item['size']}</td></tr>" for item in data["user_files"]
    )
    photos = photo_files()
    hero_photo = f"/photo/{html.escape(photos[0].name)}" if photos else ""
    preview_html = render_markdown(data["preview"])
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
    input, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #cab8ee; border-radius: 9px; padding: 9px; font: inherit; background: rgba(255,255,255,.92); }}
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
    .upload-zone {{ border: 2px dashed #d59bea; border-radius: 16px; padding: 18px; background: linear-gradient(135deg, rgba(255,255,255,.9), rgba(255,232,246,.75)); }}
    .examples {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; color: #5f4f79; font-size: 13px; }}
    .example {{ background: rgba(255,255,255,.7); border: 1px solid rgba(155,126,205,.22); border-radius: 10px; padding: 8px; }}
    @media (max-width: 760px) {{ .grid {{ grid-template-columns: 1fr; }} main {{ padding: 14px; }} }}
    @media (max-width: 980px) {{ .formgrid, .workspace {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header><div class="hero"><h1>AIGC Thesis Toolkit</h1><div class="subtitle">{html.escape(data["project"])}<br>上传资料、配置模型、连续生成小节，并实时预览已写出的正文。关闭页面不会停止后台任务，使用“关闭 WebUI”或终端 Ctrl+C 结束服务。</div></div></header>
  <main>
    <div class="bar" title="{percent}%"><span></span></div>
    <div class="grid">
      <div class="panel"><div class="label">进度</div><div class="value" id="metric-progress">{data["done"]}/{data["total"]} 小节</div></div>
      <div class="panel"><div class="label">任务</div><div class="value" id="metric-running">{running_text}</div></div>
      <div class="panel"><div class="label">暂停</div><div class="value" id="metric-paused">{paused_text}</div></div>
      <div class="panel"><div class="label">当前小节</div><div class="value" id="metric-current">{html.escape(current.get("subsection_title") or current.get("title") or "无")}</div></div>
    </div>

    <form class="actions" method="post" action="/action">
      <button class="primary" name="cmd" value="all">开始完整流程</button>
      <button name="cmd" value="generate">继续生成正文</button>
      <button class="warn" name="cmd" value="pause">暂停</button>
      <button class="good" name="cmd" value="resume">继续</button>
      <button name="cmd" value="style">自动生成规范</button>
      <button name="cmd" value="resources">刷新资料索引</button>
      <button name="cmd" value="outline">重建大纲</button>
      <button name="cmd" value="plan">重建小节计划</button>
      <button name="cmd" value="build">构建 Word</button>
      <button class="danger" name="cmd" value="shutdown">关闭 WebUI</button>
    </form>
    <div class="toolbar-note">打开：终端运行 <code>python workflow.py ui</code>。关闭：点“关闭 WebUI”，或在运行它的终端按 Ctrl+C。旧后台服务可用 <code>pkill -f workflows/webui/server.py</code> 结束。</div>

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
              <div><label>小节间隔秒数</label><input name="sleep_seconds" value="{html.escape(str(settings['sleep_seconds']))}"></div>
              <div><label>请求超时秒数</label><input name="request_timeout_seconds" value="{html.escape(str(settings['request_timeout_seconds']))}"></div>
              <div><label>本轮最多小节数，0 为不限制</label><input name="max_sections_per_run" value="{html.escape(str(settings['max_sections_per_run']))}"></div>
            </div>
            <div class="actions"><button class="primary">保存配置</button></div>
          </form>
        </section>

        <section>
          <h2>资料文件</h2>
          <form class="panel upload-zone" method="post" action="/upload" enctype="multipart/form-data">
            <h3>上传到 user_data</h3>
            <div class="muted">建议上传与论文直接相关的资料，AI 会先生成资料索引，再据此写大纲和正文。</div>
            <div class="examples">
              <div class="example">开题报告、中期报告、任务书</div>
              <div class="example">参考论文、BibTeX、文献笔记</div>
              <div class="example">仿真数据、实验数据、表格</div>
              <div class="example">原理图、流程图、实物照片</div>
            </div>
            <p><input type="file" name="files" multiple></p>
            <div class="actions"><button class="primary">上传文件</button></div>
          </form>
          <div class="panel">
            <h3>已有资料</h3>
            <table>
              <thead><tr><th>文件</th><th>大小 bytes</th></tr></thead>
              <tbody>{user_files or '<tr><td colspan="2">尚未上传资料</td></tr>'}</tbody>
            </table>
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
            <p><input type="file" name="style_file"></p>
            <div class="actions"><button class="primary">导入为 thesis/style.md</button></div>
          </form>
        </section>
      </div>

      <div class="stack">
        <section>
          <h2>实时论文预览</h2>
          <article class="panel preview" id="preview">{preview_html}</article>
        </section>
        <section>
          <h2>任务输出</h2>
          <pre id="logs">{logs or "暂无输出"}</pre>
        </section>
      </div>
    </section>

    <h2>小节计划</h2>
    <table>
      <thead><tr><th>状态</th><th>ID</th><th>章</th><th>小节</th><th>文件</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="5">尚未生成计划</td></tr>'}</tbody>
    </table>
  </main>
  <script>
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
        document.getElementById('metric-progress').textContent = `${{data.done}}/${{data.total}} 小节`;
        document.getElementById('metric-running').textContent = data.runner.running ? '运行中' : '空闲';
        document.getElementById('metric-paused').textContent = data.paused ? '已请求暂停' : '未暂停';
        document.getElementById('metric-current').textContent = (data.current && (data.current.subsection_title || data.current.title)) || '无';
        document.getElementById('logs').textContent = data.runner.output.length ? data.runner.output.join('\\n') : '暂无输出';
        document.getElementById('preview').innerHTML = renderMarkdown(data.preview || '');
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
        if parsed.path.startswith("/photo/"):
            self.send_file(PHOTO_DIR / Path(parsed.path).name)
            return
        self.send_html(render_page())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        parsed = urlparse(self.path)
        if parsed.path == "/upload":
            save_upload(self.headers.get("Content-Type", ""), raw_body)
        elif parsed.path == "/style-upload":
            save_style_upload(self.headers.get("Content-Type", ""), raw_body)
        else:
            body = raw_body.decode("utf-8")
            values = parse_qs(body)
            if parsed.path == "/settings":
                update_settings(values)
            elif parsed.path == "/style":
                update_style(values)
            else:
                cmd = values.get("cmd", [""])[0]
                if cmd == "pause":
                    set_pause(True)
                elif cmd == "resume":
                    set_pause(False)
                elif cmd == "shutdown":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write("WebUI 已关闭，可以关闭这个页面。".encode("utf-8"))
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    run_command(cmd)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def send_html(self, content):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path):
        if not path.exists() or not path.is_file() or path.parent != PHOTO_DIR:
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
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
