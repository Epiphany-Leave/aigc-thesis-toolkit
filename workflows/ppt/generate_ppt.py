#!/usr/bin/env python3
"""Generate a defense PPT from a thesis document.

The PPT workflow is intentionally separate from the thesis writer:
it accepts generated Markdown or externally supplied md/docx/pdf/txt files,
uses its own prompt, and writes independent outline/plan/preview artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"
OUTPUT_MD = WORK / "output" / "thesis.md"
OUTPUT_PPTX = WORK / "output" / "thesis_presentation.pptx"
SECTIONS_DIR = WORK / "thesis" / "sections"
PPT_DIR = WORK / "output" / "ppt"
PPT_PLAN = PPT_DIR / "plan.json"
PPT_OUTLINE = PPT_DIR / "outline.md"
PPT_PREVIEW = PPT_DIR / "preview.md"
PROMPT_FILE = WORK / "workflows" / "ppt" / "ppt_prompt.md"
MAX_SOURCE_CHARS = 70000


THEMES = {
    "infographic": {
        "bg": RGBColor(248, 250, 252),
        "panel": RGBColor(255, 255, 255),
        "accent": RGBColor(25, 118, 210),
        "accent2": RGBColor(0, 150, 136),
        "text": RGBColor(31, 41, 55),
        "muted": RGBColor(100, 116, 139),
    },
    "excalidraw": {
        "bg": RGBColor(255, 252, 242),
        "panel": RGBColor(255, 255, 255),
        "accent": RGBColor(48, 90, 176),
        "accent2": RGBColor(236, 116, 80),
        "text": RGBColor(38, 38, 38),
        "muted": RGBColor(112, 112, 112),
    },
    "architecture": {
        "bg": RGBColor(245, 247, 250),
        "panel": RGBColor(255, 255, 255),
        "accent": RGBColor(47, 72, 88),
        "accent2": RGBColor(54, 162, 235),
        "text": RGBColor(25, 33, 48),
        "muted": RGBColor(93, 105, 121),
    },
}


def clean_text(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"[*_>#|]", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def skip_heading(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    return bool(re.search(r"摘要|目录|参考文献|致谢|abstract|acknowledg", compact))


def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    result = dict(base)
    for key, value in override.items():
        result[key] = deep_merge(result.get(key), value) if key in result else value
    return result


def load_config() -> dict:
    config = {}
    if CONFIG_FILE.exists():
        config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    if LOCAL_CONFIG_FILE.exists():
        config = deep_merge(config, yaml.safe_load(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) or {})
    return config


def api_config(config: dict) -> tuple[str, str, str, int]:
    generation = config.get("engines", {}).get("generation", {})
    provider = generation.get("providers", {}).get("writer", {})
    base = (
        provider.get("api_base")
        or os.environ.get(provider.get("api_base_env", "OPENAI_BASE_URL"))
        or "https://api.openai.com/v1"
    ).rstrip("/")
    key = provider.get("api_key") or os.environ.get(provider.get("api_key_env", "OPENAI_API_KEY"), "")
    model = provider.get("model") or os.environ.get(provider.get("model_env", "OPENAI_MODEL"), "gpt-4o-mini")
    timeout = int(generation.get("batch", {}).get("request_timeout_seconds", 600))
    return base, key, model, timeout


def chat_completion(base: str, key: str, model: str, messages: list[dict], timeout: int) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.35,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                return ""
            root = ET.fromstring(archive.read("word/document.xml"))
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return ""
    texts = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
    return clean_text("\n".join(texts))


def read_pdf(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
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
    return clean_text(result.stdout) if result.returncode == 0 else ""


def source_markdown() -> str:
    if OUTPUT_MD.exists():
        return OUTPUT_MD.read_text(encoding="utf-8-sig", errors="ignore")
    parts = []
    for path in sorted(SECTIONS_DIR.rglob("*.md")):
        content = path.read_text(encoding="utf-8-sig", errors="ignore").strip()
        if content:
            parts.append(content)
    if parts:
        return "\n\n".join(parts)
    raise SystemExit("ERROR: no thesis markdown found. Run python workflow.py build first, or pass --input.")


def read_source(path: Path | None) -> tuple[str, str]:
    if path is None:
        return source_markdown(), "output/thesis.md"
    if not path.exists():
        raise SystemExit(f"ERROR: input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".markdown"}:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    elif suffix == ".docx":
        text = read_docx(path)
    elif suffix == ".pdf":
        text = read_pdf(path)
    else:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    if not text.strip():
        raise SystemExit(f"ERROR: unable to extract text from {path}. Try converting it to md/docx/pdf text first.")
    return text[:MAX_SOURCE_CHARS], str(path)


def parse_headings(text: str) -> tuple[str, list[dict]]:
    title = ""
    chapters: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        chinese_heading = re.match(r"^第[一二三四五六七八九十\d]+章\s+(.+)$", line)
        if heading or chinese_heading:
            heading_text = clean_text(heading.group(2) if heading else line)
            if not title and not skip_heading(heading_text):
                title = heading_text
            level = len(heading.group(1)) if heading else 1
            if level <= 2 and not skip_heading(heading_text) and heading_text != title:
                current = {"title": heading_text, "paragraphs": []}
                chapters.append(current)
            continue
        if current and not line.startswith(("$$", "|", "---")):
            cleaned = clean_text(line)
            if len(cleaned) >= 20:
                current["paragraphs"].append(cleaned)
    if not chapters:
        paragraphs = [clean_text(item) for item in re.split(r"\n{2,}", text) if len(clean_text(item)) > 30]
        chapters = [{"title": "论文核心内容", "paragraphs": paragraphs[:30]}]
    return title or chapters[0]["title"], chapters[:8]


def sentence_score(sentence: str) -> int:
    keywords = ["设计", "实现", "测试", "结果", "方法", "系统", "模型", "控制", "实验", "分析", "方案", "结构", "创新"]
    return len(sentence) + sum(45 for key in keywords if key in sentence)


def bullets_from_paragraphs(paragraphs: list[str], limit: int = 4) -> list[str]:
    sentences: list[str] = []
    for paragraph in paragraphs[:20]:
        sentences.extend(item.strip() for item in re.split(r"[。；;]", paragraph) if len(item.strip()) >= 12)
    ranked = sorted(sentences, key=sentence_score, reverse=True)
    bullets = []
    seen = set()
    for sentence in ranked:
        sentence = sentence[:88]
        key = sentence[:24]
        if key in seen:
            continue
        seen.add(key)
        bullets.append(sentence)
        if len(bullets) >= limit:
            break
    return bullets or ["本页内容需要结合论文正文进一步核对。"]


def local_plan(text: str, style: str, source_name: str) -> dict:
    title, chapters = parse_headings(text)
    slides = [
        {
            "title": title,
            "kind": "cover",
            "bullets": ["毕业设计（论文）答辩汇报"],
            "visual": "以课题名称为主视觉，保持正式清晰。",
            "notes": "开场说明选题背景和汇报结构。",
        },
        {
            "title": "汇报目录",
            "kind": "agenda",
            "bullets": [chapter["title"] for chapter in chapters[:6]],
            "visual": "使用流程型目录或分区导航。",
            "notes": "简要说明汇报顺序。",
        },
    ]
    for index, chapter in enumerate(chapters, start=1):
        slides.append(
            {
                "title": f"{index}. {chapter['title']}",
                "kind": "content",
                "bullets": bullets_from_paragraphs(chapter["paragraphs"]),
                "visual": "预留图解区域，可放系统结构、流程、数据图或实物照片。",
                "notes": "围绕本页要点展开说明，避免逐字朗读。",
            }
        )
    slides.append(
        {
            "title": "总结与展望",
            "kind": "summary",
            "bullets": ["总结系统设计与实现结果", "说明测试结论与不足", "给出后续优化方向"],
            "visual": "使用三段式结论图。",
            "notes": "收束贡献并自然引出提问。",
        }
    )
    return {"title": title, "style": style, "source": source_name, "slides": slides[:14]}


def ai_plan(text: str, style: str, source_name: str, config: dict) -> dict | None:
    base, key, model, timeout = api_config(config)
    if not key:
        print("PPT INFO: no API key configured, using local planner.")
        return None
    prompt = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else ""
    user = (
        f"视觉预设: {style}\n"
        f"输入来源: {source_name}\n\n"
        "请根据下面论文内容生成答辩 PPT 计划，必须返回 JSON 对象：\n"
        "{title, style, source, slides:[{title, kind, bullets, visual, notes}]}\n"
        "slides 建议 10-14 页，bullets 每页 3-5 条，每条不超过 34 个汉字。\n\n"
        f"论文内容:\n{text[:MAX_SOURCE_CHARS]}"
    )
    try:
        content = chat_completion(
            base,
            key,
            model,
            [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
            timeout,
        )
        data = json.loads(content)
    except (json.JSONDecodeError, KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"PPT WARN: AI planner failed, using local planner. {exc}")
        return None
    slides = data.get("slides") if isinstance(data, dict) else None
    if not isinstance(slides, list) or not slides:
        print("PPT WARN: AI planner returned no slides, using local planner.")
        return None
    data["title"] = str(data.get("title") or "论文答辩汇报")
    data["style"] = style
    data["source"] = source_name
    data["slides"] = normalize_slides(slides)
    return data


def normalize_slides(slides: list[dict]) -> list[dict]:
    normalized = []
    for slide in slides[:16]:
        title = clean_text(str(slide.get("title", "")))[:60] or "未命名页面"
        bullets = slide.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        bullets = [clean_text(str(item))[:80] for item in bullets if clean_text(str(item))][:5]
        normalized.append(
            {
                "title": title,
                "kind": str(slide.get("kind") or "content"),
                "bullets": bullets or ["根据论文正文提炼本页要点。"],
                "visual": clean_text(str(slide.get("visual") or "预留图解区域。"))[:120],
                "notes": clean_text(str(slide.get("notes") or ""))[:300],
            }
        )
    return normalized


def write_artifacts(plan: dict) -> None:
    PPT_DIR.mkdir(parents=True, exist_ok=True)
    PPT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    outline_lines = [f"# {plan.get('title', '论文答辩汇报')} PPT 大纲", ""]
    preview_lines = [f"# {plan.get('title', '论文答辩汇报')} PPT 预览", ""]
    for index, slide in enumerate(plan.get("slides", []), start=1):
        outline_lines.append(f"{index}. {slide['title']}（{slide.get('kind', 'content')}）")
        preview_lines.extend([f"## {index}. {slide['title']}", ""])
        preview_lines.extend(f"- {item}" for item in slide.get("bullets", []))
        if slide.get("visual"):
            preview_lines.extend(["", f"图解建议：{slide['visual']}"])
        if slide.get("notes"):
            preview_lines.extend(["", f"讲稿提示：{slide['notes']}"])
        preview_lines.append("")
    PPT_OUTLINE.write_text("\n".join(outline_lines).strip() + "\n", encoding="utf-8")
    PPT_PREVIEW.write_text("\n".join(preview_lines).strip() + "\n", encoding="utf-8")


def set_background(slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_textbox(slide, left, top, width, height, text, size=24, color=None, bold=False, align=None):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.clear()
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    paragraph.alignment = align if align is not None else PP_ALIGN.LEFT
    paragraph.word_wrap = True
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    return box


def add_bullets(slide, bullets: list[str], theme, left=0.85, top=1.55, width=5.55, height=3.6):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    for index, bullet in enumerate(bullets[:5]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = bullet
        paragraph.level = 0
        paragraph.font.size = Pt(18)
        paragraph.font.color.rgb = theme["text"]
        paragraph.space_after = Pt(8)
    return box


def add_header(slide, text: str, theme) -> None:
    add_textbox(slide, Inches(0.55), Inches(0.35), Inches(8.8), Inches(0.6), text, 24, theme["text"], True)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.08), Inches(2.35), Inches(0.05))
    line.fill.solid()
    line.fill.fore_color.rgb = theme["accent"]
    line.line.color.rgb = theme["accent"]


def add_visual_placeholder(slide, label: str, theme, style: str) -> None:
    left, top, width, height = Inches(6.65), Inches(1.55), Inches(2.7), Inches(3.95)
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = theme["panel"]
    shape.line.color.rgb = theme["accent"]
    shape.line.width = Pt(2)
    add_textbox(slide, left + Inches(0.25), top + Inches(0.25), width - Inches(0.5), Inches(0.75), label, 13, theme["accent"], True, PP_ALIGN.CENTER)
    if style == "architecture":
        for idx, name in enumerate(["输入", "处理", "输出"]):
            y = top + Inches(1.15 + idx * 0.75)
            node = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left + Inches(0.55), y, Inches(1.6), Inches(0.42))
            node.fill.solid()
            node.fill.fore_color.rgb = theme["accent2"]
            node.line.color.rgb = theme["accent2"]
            add_textbox(slide, left + Inches(0.55), y + Inches(0.06), Inches(1.6), Inches(0.26), name, 11, RGBColor(255, 255, 255), True, PP_ALIGN.CENTER)
    else:
        for idx in range(3):
            bubble = slide.shapes.add_shape(MSO_SHAPE.OVAL, left + Inches(0.45 + idx * 0.65), top + Inches(1.35 + idx * 0.48), Inches(0.78), Inches(0.78))
            bubble.fill.solid()
            bubble.fill.fore_color.rgb = theme["accent2" if idx % 2 else "accent"]
            bubble.line.color.rgb = bubble.fill.fore_color.rgb


def build_presentation(plan: dict, style: str) -> Presentation:
    theme = THEMES.get(style, THEMES["infographic"])
    slides = normalize_slides(plan.get("slides", []))
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)
    total = max(1, len(slides))
    print(f"PPT TOTAL: {total}")
    for index, item in enumerate(slides, start=1):
        print(f"PPT PROGRESS: {index}/{total} {item['title']}", flush=True)
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        set_background(slide, theme["bg"])
        kind = item.get("kind", "content")
        if kind == "cover" or index == 1:
            add_textbox(slide, Inches(0.75), Inches(1.45), Inches(8.5), Inches(1.05), item["title"], 31, theme["text"], True, PP_ALIGN.CENTER)
            subtitle = item["bullets"][0] if item.get("bullets") else "毕业设计（论文）答辩汇报"
            add_textbox(slide, Inches(1.2), Inches(2.65), Inches(7.6), Inches(0.55), subtitle, 18, theme["muted"], False, PP_ALIGN.CENTER)
            continue
        add_header(slide, item["title"], theme)
        if kind == "agenda":
            add_bullets(slide, item.get("bullets", []), theme, left=1.05, top=1.48, width=8.0)
        else:
            add_bullets(slide, item.get("bullets", []), theme)
            add_visual_placeholder(slide, item.get("visual") or "图解占位", theme, style)
    return prs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="input thesis file: md/docx/pdf/txt. Default: output/thesis.md")
    parser.add_argument("--output", default=str(OUTPUT_PPTX), help="output pptx path")
    parser.add_argument("--style", default="infographic", choices=sorted(THEMES), help="visual style preset")
    parser.add_argument("--no-ai", action="store_true", help="skip AI planning and use local extraction")
    args = parser.parse_args()

    source_path = Path(args.input) if args.input else None
    text, source_name = read_source(source_path)
    config = load_config()
    plan = None if args.no_ai else ai_plan(text, args.style, source_name, config)
    if plan is None:
        plan = local_plan(text, args.style, source_name)
    plan["slides"] = normalize_slides(plan.get("slides", []))
    write_artifacts(plan)
    prs = build_presentation(plan, args.style)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)
    print(f"OK: pptx -> {output}")
    print(f"OK: outline -> {PPT_OUTLINE}")
    print(f"OK: preview -> {PPT_PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
