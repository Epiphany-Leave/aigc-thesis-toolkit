#!/usr/bin/env python3
"""Generate a defense PPT from a thesis document.

The PPT workflow is intentionally separate from the thesis writer.  It accepts
generated Markdown or externally supplied md/docx/pdf/txt files, uses a
PPT-specific AI planning flow, and writes independent outline/plan/preview
artifacts.
"""

from __future__ import annotations

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
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
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
MAX_SOURCE_CHARS = 90000
MAX_SLIDES = 16


THEMES = {
    "infographic": {
        "bg": RGBColor(248, 250, 252),
        "panel": RGBColor(255, 255, 255),
        "panel2": RGBColor(235, 247, 255),
        "accent": RGBColor(25, 118, 210),
        "accent2": RGBColor(0, 150, 136),
        "accent3": RGBColor(251, 140, 0),
        "text": RGBColor(31, 41, 55),
        "muted": RGBColor(100, 116, 139),
    },
    "excalidraw": {
        "bg": RGBColor(255, 252, 242),
        "panel": RGBColor(255, 255, 255),
        "panel2": RGBColor(255, 244, 220),
        "accent": RGBColor(48, 90, 176),
        "accent2": RGBColor(236, 116, 80),
        "accent3": RGBColor(29, 132, 108),
        "text": RGBColor(38, 38, 38),
        "muted": RGBColor(112, 112, 112),
    },
    "architecture": {
        "bg": RGBColor(245, 247, 250),
        "panel": RGBColor(255, 255, 255),
        "panel2": RGBColor(232, 241, 248),
        "accent": RGBColor(47, 72, 88),
        "accent2": RGBColor(54, 162, 235),
        "accent3": RGBColor(0, 150, 136),
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
        local = yaml.safe_load(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) or {}
        config = deep_merge(config, local)
    return config


def api_config(config: dict) -> tuple[str, str, str, int, float]:
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
    temperature = float(generation.get("ppt_temperature", 0.45))
    return base, key, model, timeout, temperature


def chat_completion(base: str, key: str, model: str, messages: list[dict], timeout: int, temperature: float) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 7000,
        "response_format": {"type": "json_object"},
    }
    try:
        data = post_chat_completion(base, key, payload, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code not in {400, 422}:
            raise
        payload.pop("response_format", None)
        data = post_chat_completion(base, key, payload, timeout)
    return data["choices"][0]["message"]["content"]


def post_chat_completion(base: str, key: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


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


def convert_ppt_to_pptx(path: Path) -> Path | None:
    if path.suffix.lower() == ".pptx":
        return path
    if path.suffix.lower() != ".ppt" or shutil.which("libreoffice") is None:
        return None
    tmpdir = Path(tempfile.mkdtemp(prefix="ppt-template-"))
    try:
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pptx", "--outdir", str(tmpdir), str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    converted = tmpdir / f"{path.stem}.pptx"
    return converted if result.returncode == 0 and converted.exists() else None


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
        return source_markdown()[:MAX_SOURCE_CHARS], "output/thesis.md"
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


def skip_heading(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    return bool(re.search(r"摘要|目录|参考文献|致谢|abstract|acknowledg", compact))


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
        sentence = sentence[:80]
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
            "layout": "cover",
            "bullets": ["毕业论文答辩汇报"],
            "visual_type": "hero",
            "visual": "以课题名称为主视觉，保持正式、清晰、有答辩感。",
            "notes": "开场说明选题背景和汇报结构。",
        },
        {
            "title": "汇报目录",
            "kind": "agenda",
            "layout": "agenda",
            "bullets": [chapter["title"] for chapter in chapters[:6]],
            "visual_type": "timeline",
            "visual": "使用纵向流程目录，突出汇报顺序。",
            "notes": "简要说明汇报顺序。",
        },
    ]
    for index, chapter in enumerate(chapters, start=1):
        bullets = bullets_from_paragraphs(chapter["paragraphs"])
        slides.append(
            {
                "title": f"{index}. {chapter['title']}",
                "kind": "content",
                "layout": "content_visual",
                "bullets": bullets,
                "visual_type": "process" if index % 2 else "architecture",
                "visual": "根据本页要点绘制系统结构、流程、数据图或实物图占位。",
                "diagram": bullets[:4],
                "notes": "围绕本页要点展开说明，避免逐字朗读。",
            }
        )
    slides.append(
        {
            "title": "总结与展望",
            "kind": "summary",
            "layout": "summary",
            "bullets": ["总结系统设计与实现结果", "说明测试结论与不足", "给出后续优化方向"],
            "visual_type": "summary",
            "visual": "使用三段式结论图。",
            "diagram": ["完成内容", "主要结论", "后续工作"],
            "notes": "收束贡献并自然引出提问。",
        }
    )
    return {"title": title, "style": style, "source": source_name, "slides": slides[:14]}


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return "你是毕业论文答辩 PPT 总导演。必须只返回严格 JSON。"


def thesis_excerpt_for_slide(text: str, slide: dict) -> str:
    title = re.sub(r"^\d+[.、]\s*", "", str(slide.get("title", ""))).strip()
    if not title:
        return text[:18000]
    lines = text.splitlines()
    hits = [idx for idx, line in enumerate(lines) if title[:12] and title[:12] in line]
    if not hits:
        return text[:18000]
    idx = hits[0]
    start = max(0, idx - 20)
    end = min(len(lines), idx + 180)
    excerpt = "\n".join(lines[start:end])
    return excerpt[:22000]


def parse_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def ai_outline(text: str, style: str, source_name: str, config: dict) -> dict | None:
    base, key, model, timeout, temperature = api_config(config)
    if not key:
        print("PPT INFO: no API key configured, using local planner.")
        return None
    prompt = load_prompt()
    user = (
        "任务：先生成 PPT 全局故事线和每页页面蓝图，不要写满最终内容。\n"
        f"视觉预设：{style}\n"
        f"输入来源：{source_name}\n"
        "返回 JSON：{title, style, source, narrative, slides:[{title, kind, layout, purpose, evidence_hint, visual_type, visual}]}\n"
        "slides 建议 10-14 页，必须覆盖封面、目录、背景意义、方案/架构、核心实现、测试/结果、总结展望。\n\n"
        f"论文内容：\n{text[:MAX_SOURCE_CHARS]}"
    )
    try:
        print("PPT AI: generating deck outline...", flush=True)
        content = chat_completion(
            base,
            key,
            model,
            [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
            timeout,
            temperature,
        )
        data = parse_json_object(content)
    except (json.JSONDecodeError, KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"PPT WARN: AI outline failed, using local planner. {exc}")
        return None
    slides = data.get("slides") if isinstance(data, dict) else None
    if not isinstance(slides, list) or not slides:
        print("PPT WARN: AI outline returned no slides, using local planner.")
        return None
    data["title"] = str(data.get("title") or "论文答辩汇报")
    data["style"] = style
    data["source"] = source_name
    data["slides"] = slides[:MAX_SLIDES]
    return data


def ai_refine_slide(outline: dict, slide: dict, index: int, total: int, text: str, config: dict) -> dict:
    base, key, model, timeout, temperature = api_config(config)
    prompt = load_prompt()
    excerpt = thesis_excerpt_for_slide(text, slide)
    user = (
        "任务：逐页精修 PPT 页面规格。只返回这一页的 JSON 对象。\n"
        f"全局标题：{outline.get('title', '论文答辩汇报')}\n"
        f"页码：{index}/{total}\n"
        f"视觉预设：{outline.get('style', '')}\n"
        f"全局叙事：{outline.get('narrative', '')}\n"
        f"页面蓝图：{json.dumps(slide, ensure_ascii=False)}\n\n"
        "返回 JSON 字段：title, kind, layout, bullets, visual_type, visual, diagram, callout, notes。\n"
        "要求：bullets 3-5 条且每条不超过 34 个汉字；diagram 是 2-6 个可画成图形节点的短标签；"
        "callout 是本页一句结论；notes 是答辩讲稿提示。不得虚构论文没有的数据。\n\n"
        f"与本页相关的论文摘录：\n{excerpt}"
    )
    print(f"PPT AI SLIDE: {index}/{total} {slide.get('title', '')}", flush=True)
    content = chat_completion(
        base,
        key,
        model,
        [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
        timeout,
        temperature,
    )
    refined = parse_json_object(content)
    return {**slide, **refined}


def ai_plan(text: str, style: str, source_name: str, config: dict) -> dict | None:
    outline = ai_outline(text, style, source_name, config)
    if outline is None:
        return None
    base, key, _model, _timeout, _temperature = api_config(config)
    if not key or not base:
        return normalize_plan(outline)
    total = len(outline.get("slides", []))
    refined_slides = []
    for index, slide in enumerate(outline.get("slides", []), start=1):
        try:
            refined_slides.append(ai_refine_slide(outline, slide, index, total, text, config))
        except (json.JSONDecodeError, KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"PPT WARN: slide {index} refinement failed, keeping outline slide. {exc}")
            refined_slides.append(slide)
    outline["slides"] = refined_slides
    return normalize_plan(outline)


def normalize_plan(plan: dict) -> dict:
    return {
        "title": clean_text(str(plan.get("title") or "论文答辩汇报"))[:80],
        "style": str(plan.get("style") or "infographic"),
        "source": str(plan.get("source") or ""),
        "narrative": clean_text(str(plan.get("narrative") or ""))[:500],
        "slides": normalize_slides(plan.get("slides", [])),
    }


def normalize_slides(slides: list[dict]) -> list[dict]:
    normalized = []
    for slide in slides[:MAX_SLIDES]:
        if not isinstance(slide, dict):
            continue
        title = clean_text(str(slide.get("title", "")))[:60] or "未命名页面"
        bullets = slide.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        bullets = [clean_text(str(item))[:80] for item in bullets if clean_text(str(item))][:5]
        diagram = slide.get("diagram") or []
        if isinstance(diagram, str):
            diagram = [item.strip() for item in re.split(r"[,，/、;；\n]", diagram) if item.strip()]
        diagram = [clean_text(str(item))[:24] for item in diagram if clean_text(str(item))][:6]
        normalized.append(
            {
                "title": title,
                "kind": str(slide.get("kind") or "content"),
                "layout": str(slide.get("layout") or "content_visual"),
                "bullets": bullets or ["根据论文正文提炼本页要点。"],
                "visual_type": str(slide.get("visual_type") or slide.get("kind") or "process"),
                "visual": clean_text(str(slide.get("visual") or "预留图解区域。"))[:180],
                "diagram": diagram,
                "callout": clean_text(str(slide.get("callout") or ""))[:80],
                "notes": clean_text(str(slide.get("notes") or ""))[:320],
            }
        )
    return normalized


def write_artifacts(plan: dict) -> None:
    PPT_DIR.mkdir(parents=True, exist_ok=True)
    PPT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    outline_lines = [f"# {plan.get('title', '论文答辩汇报')} PPT 大纲", ""]
    preview_lines = [f"# {plan.get('title', '论文答辩汇报')} PPT 预览", ""]
    if plan.get("narrative"):
        outline_lines.extend(["## 汇报叙事", plan["narrative"], ""])
    for index, slide in enumerate(plan.get("slides", []), start=1):
        outline_lines.append(f"{index}. {slide['title']}（{slide.get('kind', 'content')}）")
        preview_lines.extend([f"## {index}. {slide['title']}", ""])
        preview_lines.extend(f"- {item}" for item in slide.get("bullets", []))
        if slide.get("callout"):
            preview_lines.extend(["", f"结论句：{slide['callout']}"])
        if slide.get("visual"):
            preview_lines.extend(["", f"图解建议：{slide['visual']}"])
        if slide.get("notes"):
            preview_lines.extend(["", f"讲稿提示：{slide['notes']}"])
        preview_lines.append("")
    PPT_OUTLINE.write_text("\n".join(outline_lines).strip() + "\n", encoding="utf-8")
    PPT_PREVIEW.write_text("\n".join(preview_lines).strip() + "\n", encoding="utf-8")


def blank_presentation(template_path: Path | None = None) -> Presentation:
    if template_path is None:
        prs = Presentation()
    else:
        template = convert_ppt_to_pptx(template_path)
        if template is None or not template.exists():
            print(f"PPT WARN: template unavailable, using default theme: {template_path}")
            prs = Presentation()
        else:
            try:
                prs = Presentation(str(template))
            except Exception as exc:
                print(f"PPT WARN: unable to read template, using default theme: {exc}")
                prs = Presentation()
    while len(prs.slides):
        slide_id = prs.slides._sldIdLst[0]
        rel_id = slide_id.rId
        prs.part.drop_rel(rel_id)
        prs.slides._sldIdLst.remove(slide_id)
    return prs


def set_background(slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def set_shape(shape, fill: RGBColor, line: RGBColor | None = None, width: int = 1) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line or fill
    shape.line.width = Pt(width)


def add_textbox(slide, left, top, width, height, text, size=24, color=None, bold=False, align=None):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(0.05)
    frame.margin_right = Inches(0.05)
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    paragraph.alignment = align if align is not None else PP_ALIGN.LEFT
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    return box


def add_bullets(slide, bullets: list[str], theme, left=0.75, top=1.55, width=5.55, height=3.35, size=17):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    for index, bullet in enumerate(bullets[:5]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = bullet
        paragraph.level = 0
        paragraph.font.size = Pt(size)
        paragraph.font.color.rgb = theme["text"]
        paragraph.space_after = Pt(8)
    return box


def add_header(slide, text: str, theme, index: int, total: int) -> None:
    add_textbox(slide, Inches(0.55), Inches(0.32), Inches(7.85), Inches(0.55), text, 23, theme["text"], True)
    add_textbox(slide, Inches(8.55), Inches(0.38), Inches(0.9), Inches(0.3), f"{index:02d}/{total:02d}", 10, theme["muted"], False, PP_ALIGN.RIGHT)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.04), Inches(2.35), Inches(0.05))
    set_shape(line, theme["accent"])


def add_callout(slide, text: str, theme) -> None:
    if not text:
        return
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.75), Inches(4.95), Inches(8.5), Inches(0.38))
    set_shape(shape, theme["panel2"], theme["accent2"], 1)
    add_textbox(slide, Inches(0.95), Inches(5.02), Inches(8.1), Inches(0.22), text, 11, theme["accent"], True, PP_ALIGN.CENTER)


def add_node(slide, x, y, w, h, text, theme, fill_key="panel", color_key="text", size=12):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    set_shape(shape, theme[fill_key], theme["accent"], 1)
    add_textbox(slide, Inches(x + 0.08), Inches(y + 0.08), Inches(w - 0.16), Inches(h - 0.12), text, size, theme[color_key], True, PP_ALIGN.CENTER)
    return shape


def add_arrow(slide, x1, y1, x2, y2, theme):
    arrow = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    arrow.line.color.rgb = theme["accent"]
    arrow.line.width = Pt(1.5)


def add_architecture_visual(slide, item: dict, theme) -> None:
    labels = item.get("diagram") or item.get("bullets", [])[:4]
    labels = (labels + ["输入", "处理", "输出"])[:4]
    left, top = 6.45, 1.45
    panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(3.0), Inches(3.35))
    set_shape(panel, theme["panel"], theme["accent"], 1)
    add_textbox(slide, Inches(left + 0.18), Inches(top + 0.15), Inches(2.64), Inches(0.35), "结构图", 12, theme["accent"], True, PP_ALIGN.CENTER)
    for idx, label in enumerate(labels[:4]):
        y = top + 0.65 + idx * 0.62
        add_node(slide, left + 0.42, y, 2.15, 0.38, label, theme, "panel2", "text", 10)
        if idx < min(len(labels), 4) - 1:
            add_arrow(slide, left + 1.5, y + 0.39, left + 1.5, y + 0.58, theme)


def add_process_visual(slide, item: dict, theme) -> None:
    labels = item.get("diagram") or item.get("bullets", [])[:4]
    labels = labels[:4] or ["问题", "方案", "实现", "验证"]
    left, top = 6.35, 1.75
    for idx, label in enumerate(labels):
        y = top + idx * 0.72
        add_node(slide, left + 0.22, y, 2.45, 0.44, label, theme, "panel2", "text", 10)
        badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(left - 0.15), Inches(y + 0.05), Inches(0.34), Inches(0.34))
        set_shape(badge, theme["accent2" if idx % 2 else "accent"])
        add_textbox(slide, Inches(left - 0.09), Inches(y + 0.1), Inches(0.22), Inches(0.16), str(idx + 1), 8, RGBColor(255, 255, 255), True, PP_ALIGN.CENTER)


def add_compare_visual(slide, item: dict, theme) -> None:
    labels = item.get("diagram") or item.get("bullets", [])[:4]
    labels = labels[:4] or ["现状", "改进", "效果"]
    left, top = 6.35, 1.55
    for idx, label in enumerate(labels[:4]):
        y = top + idx * 0.66
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left + 0.1), Inches(y + 0.28), Inches(2.35 - idx * 0.28), Inches(0.12))
        set_shape(bar, theme["accent2" if idx % 2 else "accent"])
        add_textbox(slide, Inches(left + 0.1), Inches(y), Inches(2.6), Inches(0.25), label, 11, theme["text"], True)


def add_summary_visual(slide, item: dict, theme) -> None:
    labels = item.get("diagram") or item.get("bullets", [])[:3]
    labels = labels[:3] or ["完成内容", "主要结论", "后续工作"]
    for idx, label in enumerate(labels):
        add_node(slide, 1.0 + idx * 2.95, 2.85, 2.15, 0.82, label, theme, "panel2", "text", 13)


def add_visual(slide, item: dict, theme, style: str) -> None:
    visual_type = (item.get("visual_type") or "").lower()
    if "arch" in visual_type or "架构" in visual_type or item.get("kind") == "architecture" or style == "architecture":
        add_architecture_visual(slide, item, theme)
    elif "compare" in visual_type or "对比" in visual_type or "result" in item.get("kind", ""):
        add_compare_visual(slide, item, theme)
    elif "summary" in visual_type or item.get("kind") == "summary":
        add_summary_visual(slide, item, theme)
    else:
        add_process_visual(slide, item, theme)
    add_textbox(slide, Inches(6.45), Inches(4.78), Inches(2.85), Inches(0.35), item.get("visual", ""), 9, theme["muted"], False, PP_ALIGN.CENTER)


def build_presentation(plan: dict, style: str, template_path: Path | None = None) -> Presentation:
    theme = THEMES.get(style, THEMES["infographic"])
    slides = normalize_slides(plan.get("slides", []))
    prs = blank_presentation(template_path)
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)
    total = max(1, len(slides))
    print(f"PPT TOTAL: {total}")
    for index, item in enumerate(slides, start=1):
        print(f"PPT PROGRESS: {index}/{total} {item['title']}", flush=True)
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        set_background(slide, theme["bg"])
        kind = item.get("kind", "content")
        layout = item.get("layout", "content_visual")
        if kind == "cover" or index == 1:
            add_textbox(slide, Inches(0.78), Inches(1.22), Inches(8.45), Inches(1.2), item["title"], 30, theme["text"], True, PP_ALIGN.CENTER)
            subtitle = item["bullets"][0] if item.get("bullets") else "毕业论文答辩汇报"
            add_textbox(slide, Inches(1.2), Inches(2.58), Inches(7.6), Inches(0.48), subtitle, 17, theme["muted"], False, PP_ALIGN.CENTER)
            add_summary_visual(slide, {"diagram": ["研究背景", "设计实现", "测试总结"]}, theme)
            continue
        add_header(slide, item["title"], theme, index, total)
        if kind == "agenda" or layout == "agenda":
            add_bullets(slide, item.get("bullets", []), theme, left=1.1, top=1.45, width=4.7, height=3.2, size=18)
            add_process_visual(slide, item, theme)
        elif kind == "summary" or layout == "summary":
            add_bullets(slide, item.get("bullets", []), theme, left=1.0, top=1.45, width=8.0, height=1.1, size=17)
            add_summary_visual(slide, item, theme)
        else:
            add_bullets(slide, item.get("bullets", []), theme)
            add_visual(slide, item, theme, style)
        add_callout(slide, item.get("callout", ""), theme)
    return prs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="input thesis file: md/docx/pdf/txt. Default: output/thesis.md")
    parser.add_argument("--output", default=str(OUTPUT_PPTX), help="output pptx path")
    parser.add_argument("--style", default="infographic", choices=sorted(THEMES), help="visual style preset")
    parser.add_argument("--template", help="optional reference PPT template: pptx or ppt")
    parser.add_argument("--no-ai", action="store_true", help="skip AI planning and use local extraction")
    args = parser.parse_args()

    source_path = Path(args.input) if args.input else None
    text, source_name = read_source(source_path)
    config = load_config()
    plan = None if args.no_ai else ai_plan(text, args.style, source_name, config)
    if plan is None:
        plan = normalize_plan(local_plan(text, args.style, source_name))
    else:
        plan = normalize_plan(plan)
    write_artifacts(plan)
    template_path = Path(args.template) if args.template else None
    prs = build_presentation(plan, args.style, template_path=template_path)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)
    print(f"OK: pptx -> {output}")
    print(f"OK: outline -> {PPT_OUTLINE}")
    print(f"OK: preview -> {PPT_PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
