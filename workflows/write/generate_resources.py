#!/usr/bin/env python3
"""Generate user_data/resources.md by scanning user_data with an OpenAI-compatible API."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".bib", ".tex", ".json", ".yaml", ".yml", ".log"}
OFFICE_TEXT_SUFFIXES = {".doc", ".docx", ".xlsx"}
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
BINARY_STRING_SUFFIXES = {".epro", ".schdoc", ".pcbdoc", ".prjpcb", ".json", ".xml"}
MAX_EXTRACT_CHARS_PER_FILE = 80000
MAX_EXTRACT_CHARS_PER_CHUNK = 16000
EXTRACTION_REPORT = WORK / "user_data" / "extraction_report.md"
EXTRACTION_EVENTS = {}


def extraction_key(path):
    try:
        return path.resolve().as_posix()
    except OSError:
        return str(path)


def log_extract(path, message):
    EXTRACTION_EVENTS.setdefault(extraction_key(path), []).append(message)


def extraction_notes(path):
    return EXTRACTION_EVENTS.get(extraction_key(path), [])


def load_config():
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


def api_config(config):
    provider = config.get("engines", {}).get("generation", {}).get("providers", {}).get("writer", {})
    base = (
        provider.get("api_base")
        or os.environ.get(provider.get("api_base_env", "OPENAI_BASE_URL"))
        or "https://api.openai.com/v1"
    ).rstrip("/")
    key = provider.get("api_key") or os.environ.get(provider.get("api_key_env", "OPENAI_API_KEY"), "")
    model = provider.get("model") or os.environ.get(provider.get("model_env", "OPENAI_MODEL"), "gpt-4o-mini")
    if not key:
        raise SystemExit(
            "ERROR: missing API key. Set engines.generation.providers.writer.api_key "
            "in configs/default.yaml or use the configured api_key_env."
        )
    return base, key, model


def read_text_sample(path, limit=8000):
    try:
        return path.read_text(encoding="utf-8-sig", errors="ignore")[:limit]
    except OSError:
        return ""


def read_text_content(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    try:
        return path.read_text(encoding="utf-8-sig", errors="ignore")[:limit]
    except OSError:
        return ""


def command_exists(name):
    return shutil.which(name) is not None


def clean_extracted_text(text, limit=MAX_EXTRACT_CHARS_PER_FILE):
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def run_text_command(command, timeout=60):
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def run_text_command_detail(command, timeout=60):
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "", "timeout"
    except OSError as exc:
        return "", str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return "", detail[:600] or f"exit {result.returncode}"
    return result.stdout, ""


def wsl_to_windows_path(path):
    if not command_exists("wslpath"):
        return ""
    return run_text_command(["wslpath", "-w", str(path)]).strip()


def convert_doc_with_windows_word(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    powershell = shutil.which("powershell.exe")
    if not powershell:
        log_extract(path, "Windows Word COM: powershell.exe unavailable")
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / f"{path.stem}.txt"
        input_win = wsl_to_windows_path(path)
        output_win = wsl_to_windows_path(output_path)
        if not input_win or not output_win:
            log_extract(path, "Windows Word COM: failed to map WSL path to Windows path")
            return ""
        input_win_safe = input_win.replace("'", "''")
        output_win_safe = output_win.replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop';"
            "$word=New-Object -ComObject Word.Application;"
            "$word.Visible=$false;"
            f"$doc=$word.Documents.Open('{input_win_safe}');"
            f"$doc.SaveAs([ref]'{output_win_safe}', [ref]7);"
            "$doc.Close($false);"
            "$word.Quit();"
        )
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-Command", script],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            log_extract(path, "Windows Word COM: timeout")
            return ""
        except OSError as exc:
            log_extract(path, f"Windows Word COM: {exc}")
            return ""
        if result.returncode != 0 or not output_path.exists():
            detail = (result.stderr or result.stdout or "").strip()
            log_extract(path, f"Windows Word COM failed: {detail[:600] or 'no output'}")
            return ""
        log_extract(path, "Windows Word COM: extracted text")
        return clean_extracted_text(output_path.read_text(encoding="utf-8", errors="ignore"), limit)


def convert_with_libreoffice(path, target_ext, limit=MAX_EXTRACT_CHARS_PER_FILE):
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        log_extract(path, "LibreOffice/soffice: not installed")
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                [executable, "--headless", "--convert-to", target_ext, "--outdir", tmpdir, str(path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            log_extract(path, "LibreOffice: timeout")
            return ""
        except OSError as exc:
            log_extract(path, f"LibreOffice: {exc}")
            return ""
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            log_extract(path, f"LibreOffice failed: {detail[:600] or 'no output'}")
            return ""
        converted = sorted(Path(tmpdir).glob(f"*.{target_ext.split(':', 1)[0]}"))
        if not converted:
            log_extract(path, "LibreOffice: conversion finished but no output file was produced")
            return ""
        log_extract(path, "LibreOffice: extracted text")
        return clean_extracted_text(converted[0].read_text(encoding="utf-8", errors="ignore"), limit)


def printable_byte_runs(data, limit=MAX_EXTRACT_CHARS_PER_FILE):
    parts = []
    for run in re.findall(rb"[\x09\x0a\x0d\x20-\x7e\x80-\xff]{12,}", data):
        for encoding in ("gb18030", "utf-8", "latin1"):
            text = run.decode(encoding, errors="ignore")
            if re.search(r"[\u4e00-\u9fff]", text) or len(re.findall(r"[A-Za-z]{4,}", text)) >= 3:
                cleaned = clean_extracted_text(text, limit=1800)
                if cleaned:
                    parts.append(cleaned)
                break
        if sum(len(item) for item in parts) >= limit:
            break
    return parts


def extract_binary_strings(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    parts = printable_byte_runs(data, limit=limit)
    for encoding in ("utf-16le", "utf-16be", "gb18030", "utf-8"):
        try:
            text = data.decode(encoding, errors="ignore")
        except LookupError:
            continue
        # Keep readable runs containing Chinese, Latin words, digits, or common punctuation.
        runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9，。；：、（）《》“”\"'\-_/%.℃±=+:\s]{8,}", text)
        for run in runs:
            cleaned = clean_extracted_text(run, limit=2000)
            if cleaned and len(cleaned) >= 8:
                parts.append(cleaned)
        if sum(len(item) for item in parts) >= limit:
            break
    deduped = []
    seen = set()
    for item in parts:
        key = item[:120]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return clean_extracted_text("\n".join(deduped), limit=limit)


def extract_with_strings_command(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    if not command_exists("strings"):
        log_extract(path, "strings: not installed")
        return ""
    parts = []
    for command in (["strings", "-a", "-n", "8", str(path)], ["strings", "-el", "-n", "4", str(path)]):
        text, error = run_text_command_detail(command, timeout=60)
        if text.strip():
            parts.append(text)
        elif error:
            log_extract(path, f"{command[0]} {' '.join(command[1:4])}: {error}")
    cleaned = clean_extracted_text("\n".join(parts), limit=limit)
    if cleaned:
        log_extract(path, "strings: recovered readable text fragments")
    return cleaned


def xml_text(path, names, limit=12000):
    parts = []
    try:
        with zipfile.ZipFile(path) as archive:
            for name in names:
                if name not in archive.namelist():
                    continue
                root = ET.fromstring(archive.read(name))
                texts = [node.text or "" for node in root.iter() if node.tag.endswith("}t") or node.tag.endswith("}v")]
                if texts:
                    parts.append(" ".join(texts))
                if sum(len(item) for item in parts) >= limit:
                    break
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return ""
    return "\n".join(parts)[:limit]


def read_docx_sample(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    return xml_text(path, ["word/document.xml"], limit=limit)


def read_xlsx_sample(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    names = ["xl/sharedStrings.xml"]
    try:
        with zipfile.ZipFile(path) as archive:
            names.extend(name for name in archive.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", name))
    except (OSError, zipfile.BadZipFile):
        return ""
    return xml_text(path, names, limit=limit)


def read_doc_sample(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    # Some .doc files are actually renamed .docx files.
    if zipfile.is_zipfile(path):
        text = read_docx_sample(path, limit=limit)
        if text.strip():
            log_extract(path, "ZIP/DOCX parser: extracted text from renamed .doc")
            return text
        log_extract(path, "ZIP/DOCX parser: no document text found")
    converted = convert_with_libreoffice(path, "txt:Text", limit=limit)
    if converted.strip():
        return converted
    if command_exists("antiword"):
        text, error = run_text_command_detail(["antiword", str(path)])
        if text.strip():
            log_extract(path, "antiword: extracted text")
            return clean_extracted_text(text, limit)
        log_extract(path, f"antiword failed: {error or 'no text output'}")
    else:
        log_extract(path, "antiword: not installed")
    if command_exists("catdoc"):
        text, error = run_text_command_detail(["catdoc", "-w", str(path)])
        if text.strip():
            log_extract(path, "catdoc: extracted text")
            return clean_extracted_text(text, limit)
        log_extract(path, f"catdoc failed: {error or 'no text output'}")
    else:
        log_extract(path, "catdoc: not installed")
    word_text = convert_doc_with_windows_word(path, limit=limit)
    if word_text.strip():
        return word_text
    strings_text = extract_with_strings_command(path, limit=limit)
    if strings_text.strip():
        return strings_text
    fallback = extract_binary_strings(path, limit=limit)
    if fallback.strip():
        log_extract(path, "binary fallback: recovered readable text fragments")
    else:
        log_extract(path, "binary fallback: no readable text recovered")
    return fallback


def read_pdf_sample(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    if command_exists("pdftotext"):
        text, error = run_text_command_detail(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], timeout=90)
        if text.strip():
            log_extract(path, "pdftotext: extracted text")
            return clean_extracted_text(text, limit)
        log_extract(path, f"pdftotext failed or found no text: {error or 'no text output'}")
    else:
        log_extract(path, "pdftotext: not installed")
    return ""


def read_image_ocr_sample(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    if not command_exists("tesseract"):
        log_extract(path, "tesseract OCR: not installed")
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_base = Path(tmpdir) / "ocr"
        try:
            result = subprocess.run(
                ["tesseract", str(path), str(output_base), "-l", "chi_sim+eng"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            log_extract(path, "tesseract OCR: timeout")
            return ""
        except OSError as exc:
            log_extract(path, f"tesseract OCR: {exc}")
            return ""
        output_path = output_base.with_suffix(".txt")
        if result.returncode != 0 or not output_path.exists():
            detail = (result.stderr or result.stdout or "").strip()
            log_extract(path, f"tesseract OCR failed: {detail[:600] or 'no output'}")
            return ""
        log_extract(path, "tesseract OCR: extracted text")
        return clean_extracted_text(output_path.read_text(encoding="utf-8", errors="ignore"), limit)


def read_office_sample(path, suffix=None):
    suffix = suffix or path.suffix.lower()
    if suffix == ".doc":
        return read_doc_sample(path)
    if suffix == ".docx":
        return read_docx_sample(path)
    if suffix == ".xlsx":
        return read_xlsx_sample(path)
    return ""


def repaired_multipart_relative(relative):
    if "Content-Type" not in relative:
        return relative, False
    candidate = relative.split("Content-Type", 1)[0]
    candidate = re.sub(r"[\x00-\x1f\uf000-\uf8ff]+", "", candidate)
    candidate = candidate.rstrip(' "_-:/\\')
    return (candidate or relative), bool(candidate)


def make_entry(path, relative, kind, size, content, readable, repaired=False):
    notes = list(extraction_notes(path))
    if repaired:
        notes.insert(0, "检测到旧版 WebUI 导入产生的异常 multipart 路径；已按文件名尝试补救读取，建议用新版 WebUI 重新导入。")
    return {
        "path": relative,
        "type": kind,
        "size": size,
        "content": content,
        "readable": readable,
        "notes": notes,
        "repaired": repaired,
    }


def scan_user_data_entries(user_data_dir):
    entries = []
    if not user_data_dir.exists():
        return entries

    for path in sorted(user_data_dir.rglob("*")):
        if path.is_dir() or path.name == "resources.md":
            continue
        raw_relative = path.relative_to(user_data_dir).as_posix()
        relative, repaired = repaired_multipart_relative(raw_relative)
        suffix = Path(relative).suffix.lower() or path.suffix.lower()
        size = path.stat().st_size if path.exists() else 0
        if suffix in TEXT_SUFFIXES:
            content = read_text_content(path)
            entries.append({"path": relative, "type": "文本", "size": size, "content": content, "readable": True})
        elif suffix in OFFICE_TEXT_SUFFIXES:
            sample = read_office_sample(path)
            if sample.strip():
                entries.append({"path": relative, "type": "Office 可抽取文本", "size": size, "content": sample, "readable": True})
            else:
                entries.append({"path": relative, "type": "Office 文件", "size": size, "content": "", "readable": False})
        elif suffix in PDF_SUFFIXES:
            sample = read_pdf_sample(path)
            if sample.strip():
                entries.append({"path": relative, "type": "PDF 可抽取文本", "size": size, "content": sample, "readable": True})
            else:
                entries.append({"path": relative, "type": "PDF 扫描件或不可抽取文本", "size": size, "content": "", "readable": False})
        elif suffix in IMAGE_SUFFIXES:
            sample = read_image_ocr_sample(path)
            if sample.strip():
                entries.append({"path": relative, "type": "图片 OCR 文本", "size": size, "content": sample, "readable": True})
            else:
                entries.append({"path": relative, "type": "图片文件", "size": size, "content": "", "readable": False})
        elif suffix in BINARY_STRING_SUFFIXES:
            sample = extract_binary_strings(path)
            if sample.strip():
                entries.append({"path": relative, "type": "工程/二进制可恢复字符串", "size": size, "content": sample, "readable": True})
            else:
                entries.append({"path": relative, "type": "工程/二进制文件", "size": size, "content": "", "readable": False})
        else:
            entries.append({"path": relative, "type": "二进制/PDF/图片/工程文件", "size": size, "content": "", "readable": False})
    return entries


def scan_user_data_entries_v2(user_data_dir):
    entries = []
    if not user_data_dir.exists():
        return entries

    for path in sorted(user_data_dir.rglob("*")):
        if path.is_dir() or path.name in {"resources.md", "extraction_report.md"}:
            continue
        raw_relative = path.relative_to(user_data_dir).as_posix()
        relative, repaired = repaired_multipart_relative(raw_relative)
        suffix = Path(relative).suffix.lower() or path.suffix.lower()
        size = path.stat().st_size if path.exists() else 0
        if suffix in TEXT_SUFFIXES:
            content = read_text_content(path)
            entries.append(make_entry(path, relative, "文本", size, content, True, repaired))
        elif suffix in OFFICE_TEXT_SUFFIXES:
            sample = read_office_sample(path, suffix=suffix)
            entries.append(make_entry(path, relative, "Office 可抽取文本" if sample.strip() else "Office 文件", size, sample if sample.strip() else "", bool(sample.strip()), repaired))
        elif suffix in PDF_SUFFIXES:
            sample = read_pdf_sample(path)
            entries.append(make_entry(path, relative, "PDF 可抽取文本" if sample.strip() else "PDF 扫描件或不可抽取文本", size, sample if sample.strip() else "", bool(sample.strip()), repaired))
        elif suffix in IMAGE_SUFFIXES:
            sample = read_image_ocr_sample(path)
            entries.append(make_entry(path, relative, "图片 OCR 文本" if sample.strip() else "图片文件", size, sample if sample.strip() else "", bool(sample.strip()), repaired))
        elif suffix in BINARY_STRING_SUFFIXES:
            sample = extract_with_strings_command(path) or extract_binary_strings(path)
            entries.append(make_entry(path, relative, "工程/二进制可恢复字符串" if sample.strip() else "工程/二进制文件", size, sample if sample.strip() else "", bool(sample.strip()), repaired))
        else:
            sample = extract_with_strings_command(path)
            entries.append(make_entry(path, relative, "未知扩展名但已恢复文本" if sample.strip() else "二进制/PDF/图片/工程文件", size, sample if sample.strip() else "", bool(sample.strip()), repaired))
    return entries


scan_user_data_entries = scan_user_data_entries_v2


def scan_user_data(user_data_dir):
    entries = scan_user_data_entries(user_data_dir)
    write_extraction_report(entries)
    print(f"OK: wrote extraction diagnostics to {EXTRACTION_REPORT}")

    if not entries:
        return "user_data 目录为空。"
    rendered = []
    for entry in entries:
        if entry["readable"]:
            rendered.append(f"## {entry['path']}\n类型：{entry['type']}；大小：{entry['size']} bytes\n\n{entry['content'][:8000]}")
        else:
            rendered.append(f"## {entry['path']}\n类型：{entry['type']}；大小：{entry['size']} bytes；未能抽取正文，只能作为文件名线索。\n")
    return "\n\n".join(rendered)[:70000]


def split_text(text, max_chars=MAX_EXTRACT_CHARS_PER_CHUNK):
    if len(text) <= max_chars:
        return [text]
    chunks = []
    current = []
    size = 0
    for part in re.split(r"(\n\s*\n)", text):
        if size + len(part) > max_chars and current:
            chunks.append("".join(current).strip())
            current = []
            size = 0
        current.append(part)
        size += len(part)
    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def build_messages(project_title, inventory):
    return [
        {
            "role": "system",
            "content": (
                "你是论文资料整理助手。根据用户目录扫描结果生成可追踪的资料索引。"
                "只输出 Markdown，不解释过程，不编造不存在的文件、数据、实验结果或文献。"
            ),
        },
        {
            "role": "user",
            "content": f"""请根据 user_data 扫描结果生成 user_data/resources.md。

论文题目：{project_title}

扫描结果：
{inventory}

输出要求：
1. 一级标题为“# 个人资料索引”。
2. 按“课题信息”“可用文本资料”“可用图表/仿真/实验资料”“参考文献线索”“缺口与待补充资料”组织。
3. 每条资料必须保留可追踪文件路径。
4. 对已经抽取出文本的 Office、PDF、OCR 或工程字符串内容，可以基于抽取片段总结；对仍无法抽取正文的 PDF、图片、二进制文件，只能根据文件名和路径判断用途，不要声称已读取其中内容。
5. 如果资料不足，明确写出缺口，不要补造参数、实验或结论。
""",
        },
    ]


def build_extract_messages(project_title, entry, chunk, index, total):
    return [
        {
            "role": "system",
            "content": (
                "你是论文资料深度提取助手。你需要从单个 user_data 文件片段中提取可用于论文写作的事实。"
                "只输出 Markdown，不扩写正文，不编造不存在的信息。"
            ),
        },
        {
            "role": "user",
            "content": f"""论文题目：{project_title}

文件路径：{entry['path']}
文件类型：{entry['type']}
片段：{index}/{total}

请提取：
- 与课题直接相关的事实、参数、器件型号、实验条件、测试数据、结论
- 文档中出现的参考文献、引用编号、文献题名、作者、期刊/会议、年份、DOI 或 URL
- 可作为图表、公式、章节内容依据的信息
- 文件中明确提到但仍需人工核查的点
- 资料缺口

要求：
1. 每条都保留文件路径。
2. 不要写泛泛而谈的总结。
3. 不要补造文件里没有的数据。

文件片段：
{chunk}
""",
        },
    ]


def ai_extract_inventory(config, entries, base, key, model, timeout):
    project_title = config.get("project", {}).get("title", "")
    parts = ["# AI 资料抽取结果"]
    for entry in entries:
        if not entry["readable"] or not entry["content"].strip():
            parts.append(
                f"## {entry['path']}\n- 类型：{entry['type']}\n- 状态：未能抽取正文，只能作为文件名和路径线索。"
            )
            continue
        chunks = split_text(entry["content"])
        parts.append(f"## {entry['path']}\n- 类型：{entry['type']}\n- 大小：{entry['size']} bytes")
        for index, chunk in enumerate(chunks, start=1):
            print(f"EXTRACT: {entry['path']} {index}/{len(chunks)}")
            extracted = chat_completion(
                base,
                key,
                model,
                build_extract_messages(project_title, entry, chunk, index, len(chunks)),
                timeout,
            )
            parts.append(f"\n### 片段 {index}/{len(chunks)}\n{extracted}")
    return "\n\n".join(parts)[:220000]


def ai_extract_inventory_v2(config, entries, base, key, model, timeout):
    project_title = config.get("project", {}).get("title", "")
    parts = ["# AI 资料抽取结果"]
    for entry in entries:
        notes = "\n".join(f"- 抽取诊断：{note}" for note in entry.get("notes", [])[-6:])
        if not entry["readable"] or not entry["content"].strip():
            parts.append(
                f"## {entry['path']}\n- 类型：{entry['type']}\n- 状态：未能抽取正文，只能作为文件名和路径线索。\n{notes}"
            )
            continue
        chunks = split_text(entry["content"])
        parts.append(f"## {entry['path']}\n- 类型：{entry['type']}\n- 大小：{entry['size']} bytes\n{notes}")
        for index, chunk in enumerate(chunks, start=1):
            print(f"EXTRACT: {entry['path']} {index}/{len(chunks)}")
            extracted = chat_completion(
                base,
                key,
                model,
                build_extract_messages(project_title, entry, chunk, index, len(chunks)),
                timeout,
            )
            parts.append(f"\n### 片段 {index}/{len(chunks)}\n{extracted}")
    return "\n\n".join(parts)[:220000]


ai_extract_inventory = ai_extract_inventory_v2


def write_extraction_report(entries):
    lines = ["# user_data 抽取诊断报告", ""]
    if not entries:
        lines.append("user_data 目录为空。")
    for entry in entries:
        state = "成功" if entry.get("readable") and entry.get("content", "").strip() else "失败"
        lines.append(f"## {entry['path']}")
        lines.append(f"- 状态：{state}")
        lines.append(f"- 类型：{entry['type']}")
        lines.append(f"- 大小：{entry['size']} bytes")
        if entry.get("content"):
            lines.append(f"- 已抽取字符数：{len(entry['content'])}")
        if entry.get("notes"):
            for note in entry["notes"]:
                lines.append(f"- 诊断：{note}")
        if state == "失败":
            lines.append("- 建议：在 WSL 安装 libreoffice/antiword/catdoc/poppler-utils/tesseract-ocr，或将该文件另存为 docx/pdf/txt 后重新导入。")
        lines.append("")
    EXTRACTION_REPORT.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def chat_completion(base, key, model, messages, timeout):
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": model, "messages": messages, "temperature": 0.1}, ensure_ascii=False).encode(
            "utf-8"
        ),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"ERROR: API request failed: {exc.code}\n{detail}") from exc
    return data["choices"][0]["message"]["content"].strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing user_data/resources.md")
    args = parser.parse_args()

    config = load_config()
    user_data_dir = WORK / config.get("paths", {}).get("user_data_dir", "user_data")
    output_path = user_data_dir / "resources.md"
    if output_path.exists() and not args.overwrite:
        print(f"SKIP: exists: {output_path}. Use --overwrite to refresh.")
        return 0

    user_data_dir.mkdir(parents=True, exist_ok=True)
    base, key, model = api_config(config)
    timeout = int(config.get("engines", {}).get("generation", {}).get("batch", {}).get("request_timeout_seconds", 180))
    entries = scan_user_data_entries(user_data_dir)
    inventory = ai_extract_inventory(config, entries, base, key, model, timeout) if entries else "user_data 目录为空。"
    content = chat_completion(
        base,
        key,
        model,
        build_messages(config.get("project", {}).get("title", ""), inventory),
        timeout,
    )
    output_path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"OK: generated {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
