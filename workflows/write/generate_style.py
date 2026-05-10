#!/usr/bin/env python3
"""Generate thesis/style.md by scanning user_data with an OpenAI-compatible API."""

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
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".bib", ".tex", ".json", ".yaml", ".yml"}
OFFICE_TEXT_SUFFIXES = {".doc", ".docx", ".xlsx"}
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
MAX_SAMPLE_CHARS = 60000


def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    result = dict(base)
    for key, value in override.items():
        result[key] = deep_merge(result.get(key), value) if key in result else value
    return result


def load_config():
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    if LOCAL_CONFIG_FILE.exists():
        config = deep_merge(config, yaml.safe_load(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) or {})
    return config


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
            "ERROR: missing API key. Set it in the WebUI, configs/local.yaml, "
            "or the configured api_key_env."
        )
    return base, key, model


def read_text_sample(path, limit=9000):
    try:
        return path.read_text(encoding="utf-8-sig", errors="ignore")[:limit]
    except OSError:
        return ""


def command_exists(name):
    return shutil.which(name) is not None


def clean_extracted_text(text, limit=MAX_SAMPLE_CHARS):
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


def convert_doc_with_windows_word(path, limit=MAX_SAMPLE_CHARS):
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


def convert_with_libreoffice(path, target_ext, limit=MAX_SAMPLE_CHARS):
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


def printable_byte_runs(data, limit=MAX_SAMPLE_CHARS):
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


def extract_binary_strings(path, limit=MAX_SAMPLE_CHARS):
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    parts = printable_byte_runs(data, limit=limit)
    for encoding in ("utf-16le", "utf-16be", "gb18030", "utf-8"):
        text = data.decode(encoding, errors="ignore")
        runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9，。；：、（）《》“”\"'\-_/%.℃±=+:\s]{8,}", text)
        parts.extend(clean_extracted_text(run, limit=1800) for run in runs)
        if sum(len(item) for item in parts) >= limit:
            break
    deduped = []
    seen = set()
    for item in parts:
        if not item:
            continue
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


def read_office_sample(path):
    suffix = path.suffix.lower()
    if suffix == ".doc":
        if zipfile.is_zipfile(path):
            text = xml_text(path, ["word/document.xml"], limit=MAX_SAMPLE_CHARS)
            if text.strip():
                return text
        converted = convert_with_libreoffice(path, "txt:Text")
        if converted.strip():
            return converted
        if command_exists("antiword"):
            text = run_text_command(["antiword", str(path)])
            if text.strip():
                return clean_extracted_text(text)
        if command_exists("catdoc"):
            text = run_text_command(["catdoc", "-w", str(path)])
            if text.strip():
                return clean_extracted_text(text)
        word_text = convert_doc_with_windows_word(path)
        if word_text.strip():
            return word_text
        return extract_binary_strings(path)
    if suffix == ".docx":
        return xml_text(path, ["word/document.xml"])
    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(path) as archive:
                names = ["xl/sharedStrings.xml"]
                names.extend(name for name in archive.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", name))
        except (OSError, zipfile.BadZipFile):
            return ""
        return xml_text(path, names)
    return ""


def read_pdf_sample(path):
    if not command_exists("pdftotext"):
        return ""
    return clean_extracted_text(run_text_command(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], timeout=90))


def read_image_ocr_sample(path):
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
        return clean_extracted_text(output_path.read_text(encoding="utf-8", errors="ignore"))


def scan_user_data(user_data_dir):
    if not user_data_dir.exists():
        return "user_data 目录不存在。"

    entries = []
    for path in sorted(user_data_dir.rglob("*")):
        if path.is_dir() or path.name == "resources.md":
            continue
        relative = path.relative_to(user_data_dir).as_posix()
        suffix = path.suffix.lower()
        size = path.stat().st_size if path.exists() else 0
        if suffix in TEXT_SUFFIXES:
            entries.append(f"## {relative}\n类型：文本；大小：{size} bytes\n\n{read_text_sample(path)}")
        elif suffix in OFFICE_TEXT_SUFFIXES:
            sample = read_office_sample(path)
            if sample.strip():
                entries.append(f"## {relative}\n类型：Office 可抽取文本；大小：{size} bytes\n\n{sample}")
            else:
                entries.append(f"## {relative}\n类型：Office 文件；大小：{size} bytes；未能抽取正文，只能作为文件名线索。\n")
        elif suffix in PDF_SUFFIXES:
            sample = read_pdf_sample(path)
            if sample.strip():
                entries.append(f"## {relative}\n类型：PDF 可抽取文本；大小：{size} bytes\n\n{sample}")
            else:
                entries.append(f"## {relative}\n类型：PDF 扫描件或不可抽取文本；大小：{size} bytes\n")
        elif suffix in IMAGE_SUFFIXES:
            sample = read_image_ocr_sample(path)
            if sample.strip():
                entries.append(f"## {relative}\n类型：图片 OCR 文本；大小：{size} bytes\n\n{sample}")
            else:
                entries.append(f"## {relative}\n类型：图片文件；大小：{size} bytes；未安装 tesseract 时只能作为图片线索。\n")
        else:
            entries.append(f"## {relative}\n类型：二进制/Office/PDF/图片等；大小：{size} bytes\n")
    return "\n\n".join(entries)[:70000] if entries else "user_data 目录为空。"


def looks_placeholder_style(text):
    normalized = text.strip()
    if not normalized:
        return True
    markers = [
        "写作与格式规范",
        "使用本科毕业论文的正式学术表达",
        "章节内容按照自动生成的 thesis/outline.md 展开",
    ]
    return all(marker in normalized for marker in markers) and len(normalized) < 800


def build_messages(project_title, inventory):
    return [
        {
            "role": "system",
            "content": (
                "你是本科毕业论文格式规范整理助手。根据用户资料中的学校要求、模板、报告、"
                "论文范例和文件名线索，生成可执行的 thesis/style.md。只输出 Markdown。"
                "不要编造学校没有给出的硬性格式；不确定的地方写成建议或 TODO。"
            ),
        },
        {
            "role": "user",
            "content": f"""请为本项目生成 thesis/style.md。

论文题目：{project_title}

user_data 扫描结果：
{inventory}

输出要求：
1. 一级标题为“# 写作与格式规范”。
2. 至少包含：整体文风、章节结构、标题层级、公式、图题、表题、引用、数据真实性、Word 导出注意事项。
3. 如果资料中出现学校模板、任务书、开题报告、中期报告、范例论文，请提取其中能确定的写作规范。
4. 对已经抽取出文本的 Office、PDF、OCR 内容，可以基于抽取片段总结；对无法抽取文本的 PDF、图片、二进制文件，只能依据文件名判断可能用途，不要声称已读取其中内容。
5. 不要输出代码块。
""",
        },
    ]


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
    parser.add_argument("--overwrite", action="store_true", help="overwrite custom thesis/style.md")
    args = parser.parse_args()

    config = load_config()
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    user_data_dir = WORK / config.get("paths", {}).get("user_data_dir", "user_data")
    style_path = thesis_dir / "style.md"

    current = style_path.read_text(encoding="utf-8-sig") if style_path.exists() else ""
    if current and not args.overwrite and not looks_placeholder_style(current):
        print(f"SKIP: custom style exists: {style_path}. Use --overwrite to refresh.")
        return 0

    thesis_dir.mkdir(parents=True, exist_ok=True)
    base, key, model = api_config(config)
    timeout = int(config.get("engines", {}).get("generation", {}).get("batch", {}).get("request_timeout_seconds", 180))
    content = chat_completion(
        base,
        key,
        model,
        build_messages(config.get("project", {}).get("title", ""), scan_user_data(user_data_dir)),
        timeout,
    )
    style_path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"OK: generated {style_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
