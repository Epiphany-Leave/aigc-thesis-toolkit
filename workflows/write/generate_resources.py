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


def wsl_to_windows_path(path):
    if not command_exists("wslpath"):
        return ""
    return run_text_command(["wslpath", "-w", str(path)]).strip()


def convert_doc_with_windows_word(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    powershell = shutil.which("powershell.exe")
    if not powershell:
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / f"{path.stem}.txt"
        input_win = wsl_to_windows_path(path)
        output_win = wsl_to_windows_path(output_path)
        if not input_win or not output_win:
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
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0 or not output_path.exists():
            return ""
        return clean_extracted_text(output_path.read_text(encoding="utf-8", errors="ignore"), limit)


def convert_with_libreoffice(path, target_ext, limit=MAX_EXTRACT_CHARS_PER_FILE):
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
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
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        converted = sorted(Path(tmpdir).glob(f"*.{target_ext.split(':', 1)[0]}"))
        if not converted:
            return ""
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
            return text
    converted = convert_with_libreoffice(path, "txt:Text", limit=limit)
    if converted.strip():
        return converted
    if command_exists("antiword"):
        text = run_text_command(["antiword", str(path)])
        if text.strip():
            return clean_extracted_text(text, limit)
    if command_exists("catdoc"):
        text = run_text_command(["catdoc", "-w", str(path)])
        if text.strip():
            return clean_extracted_text(text, limit)
    word_text = convert_doc_with_windows_word(path, limit=limit)
    if word_text.strip():
        return word_text
    return extract_binary_strings(path, limit=limit)


def read_pdf_sample(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    if command_exists("pdftotext"):
        text = run_text_command(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], timeout=90)
        if text.strip():
            return clean_extracted_text(text, limit)
    return ""


def read_image_ocr_sample(path, limit=MAX_EXTRACT_CHARS_PER_FILE):
    if not command_exists("tesseract"):
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
        except (OSError, subprocess.TimeoutExpired):
            return ""
        output_path = output_base.with_suffix(".txt")
        if result.returncode != 0 or not output_path.exists():
            return ""
        return clean_extracted_text(output_path.read_text(encoding="utf-8", errors="ignore"), limit)


def read_office_sample(path):
    suffix = path.suffix.lower()
    if suffix == ".doc":
        return read_doc_sample(path)
    if suffix == ".docx":
        return read_docx_sample(path)
    if suffix == ".xlsx":
        return read_xlsx_sample(path)
    return ""


def scan_user_data_entries(user_data_dir):
    entries = []
    if not user_data_dir.exists():
        return entries

    for path in sorted(user_data_dir.rglob("*")):
        if path.is_dir() or path.name == "resources.md":
            continue
        relative = path.relative_to(user_data_dir).as_posix()
        suffix = path.suffix.lower()
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


def scan_user_data(user_data_dir):
    entries = scan_user_data_entries(user_data_dir)

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
