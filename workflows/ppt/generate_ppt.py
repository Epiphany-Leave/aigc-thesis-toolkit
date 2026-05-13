#!/usr/bin/env python3
"""Generate a PowerPoint deck from the generated thesis Markdown."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


WORK = Path(__file__).resolve().parents[2]
OUTPUT_MD = WORK / "output" / "thesis.md"
OUTPUT_PPTX = WORK / "output" / "thesis_presentation.pptx"
SECTIONS_DIR = WORK / "thesis" / "sections"


THEMES = {
    "infographic": {
        "bg": RGBColor(248, 250, 252),
        "accent": RGBColor(25, 118, 210),
        "accent2": RGBColor(0, 150, 136),
        "text": RGBColor(31, 41, 55),
        "muted": RGBColor(100, 116, 139),
    },
    "excalidraw": {
        "bg": RGBColor(255, 252, 242),
        "accent": RGBColor(48, 90, 176),
        "accent2": RGBColor(236, 116, 80),
        "text": RGBColor(38, 38, 38),
        "muted": RGBColor(112, 112, 112),
    },
    "architecture": {
        "bg": RGBColor(245, 247, 250),
        "accent": RGBColor(47, 72, 88),
        "accent2": RGBColor(54, 162, 235),
        "text": RGBColor(25, 33, 48),
        "muted": RGBColor(93, 105, 121),
    },
}


@dataclass
class Chapter:
    title: str
    paragraphs: list[str]


def clean_text(text: str) -> str:
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", "", text)
    text = re.sub(r"[*_>#|]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
    raise SystemExit("ERROR: no thesis markdown found. Run python workflow.py build first, or generate sections.")


def parse_chapters(markdown: str) -> tuple[str, list[Chapter]]:
    title = ""
    chapters: list[Chapter] = []
    current: Chapter | None = None
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            text = clean_text(heading.group(2))
            if level == 1 and not title and text not in {"摘要", "目录", "参考文献", "致谢"}:
                title = text
            if level <= 2 and text not in {"摘要", "目录", "参考文献", "致谢"}:
                current = Chapter(text, [])
                chapters.append(current)
            continue
        if current and not line.startswith(("$$", "|", "---")):
            text = clean_text(line)
            if len(text) >= 18 and not re.match(r"^图\d|^表\d", text):
                current.paragraphs.append(text)
    if not title:
        title = chapters[0].title if chapters else "论文汇报"
    return title, chapters[:8]


def sentence_score(sentence: str) -> int:
    keywords = ["设计", "实现", "测试", "结果", "方法", "系统", "模型", "控制", "实验", "分析", "方案", "结构"]
    return len(sentence) + sum(40 for key in keywords if key in sentence)


def chapter_bullets(chapter: Chapter, limit: int = 4) -> list[str]:
    sentences: list[str] = []
    for paragraph in chapter.paragraphs[:18]:
        sentences.extend(item.strip() for item in re.split(r"[。；;]", paragraph) if len(item.strip()) >= 12)
    ranked = sorted(sentences, key=sentence_score, reverse=True)
    bullets = []
    seen = set()
    for sentence in ranked:
        sentence = sentence[:82]
        key = sentence[:24]
        if key in seen:
            continue
        seen.add(key)
        bullets.append(sentence)
        if len(bullets) >= limit:
            break
    return bullets or ["本章内容需要结合生成论文进一步人工核查。"]


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
    if align is not None:
        paragraph.alignment = align
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    return box


def add_bullets(slide, bullets: list[str], theme, left=0.95, top=1.65, width=8.4, height=4.6):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    for index, bullet in enumerate(bullets):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = bullet
        paragraph.level = 0
        paragraph.font.size = Pt(20)
        paragraph.font.color.rgb = theme["text"]
        paragraph.space_after = Pt(8)
    return box


def add_header(slide, text: str, theme) -> None:
    add_textbox(slide, Inches(0.55), Inches(0.35), Inches(9.0), Inches(0.55), text, 26, theme["text"], True)
    line = slide.shapes.add_shape(1, Inches(0.55), Inches(1.05), Inches(2.2), Inches(0.05))
    line.fill.solid()
    line.fill.fore_color.rgb = theme["accent"]
    line.line.color.rgb = theme["accent"]


def add_visual_placeholder(slide, label: str, theme, style: str) -> None:
    left, top, width, height = Inches(6.6), Inches(1.55), Inches(2.7), Inches(4.45)
    shape = slide.shapes.add_shape(1, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(255, 255, 255)
    shape.line.color.rgb = theme["accent"]
    shape.line.width = Pt(2)
    add_textbox(slide, left + Inches(0.25), top + Inches(0.35), width - Inches(0.5), Inches(0.5), label, 15, theme["accent"], True, PP_ALIGN.CENTER)
    if style == "architecture":
        for idx, name in enumerate(["输入", "处理", "输出"]):
            y = top + Inches(1.15 + idx * 0.9)
            node = slide.shapes.add_shape(1, left + Inches(0.55), y, Inches(1.6), Inches(0.45))
            node.fill.solid()
            node.fill.fore_color.rgb = theme["accent2"]
            node.line.color.rgb = theme["accent2"]
            add_textbox(slide, left + Inches(0.55), y + Inches(0.06), Inches(1.6), Inches(0.3), name, 12, RGBColor(255, 255, 255), True, PP_ALIGN.CENTER)
    else:
        for idx in range(3):
            bubble = slide.shapes.add_shape(9, left + Inches(0.45 + idx * 0.65), top + Inches(1.45 + idx * 0.55), Inches(0.85), Inches(0.85))
            bubble.fill.solid()
            bubble.fill.fore_color.rgb = theme["accent2" if idx % 2 else "accent"]
            bubble.line.color.rgb = bubble.fill.fore_color.rgb


def build_presentation(title: str, chapters: list[Chapter], style: str) -> Presentation:
    theme = THEMES.get(style, THEMES["infographic"])
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_background(slide, theme["bg"])
    add_textbox(slide, Inches(0.75), Inches(1.55), Inches(8.5), Inches(1.0), title, 34, theme["text"], True, PP_ALIGN.CENTER)
    add_textbox(slide, Inches(1.2), Inches(2.65), Inches(7.6), Inches(0.55), "论文答辩汇报", 20, theme["muted"], False, PP_ALIGN.CENTER)

    agenda = prs.slides.add_slide(prs.slide_layouts[6])
    set_background(agenda, theme["bg"])
    add_header(agenda, "汇报目录", theme)
    add_bullets(agenda, [chapter.title for chapter in chapters[:6]], theme, left=1.0, top=1.45, width=8.0)

    for index, chapter in enumerate(chapters, start=1):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        set_background(slide, theme["bg"])
        add_header(slide, f"{index}. {chapter.title}", theme)
        add_bullets(slide, chapter_bullets(chapter), theme, left=0.75, top=1.45, width=5.55)
        add_visual_placeholder(slide, "图解占位", theme, style)

    ending = prs.slides.add_slide(prs.slide_layouts[6])
    set_background(ending, theme["bg"])
    add_textbox(ending, Inches(1.0), Inches(2.0), Inches(8.0), Inches(0.8), "谢谢观看", 40, theme["text"], True, PP_ALIGN.CENTER)
    add_textbox(ending, Inches(1.0), Inches(2.85), Inches(8.0), Inches(0.45), "Q & A", 22, theme["accent"], True, PP_ALIGN.CENTER)
    return prs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(OUTPUT_MD), help="input thesis markdown path")
    parser.add_argument("--output", default=str(OUTPUT_PPTX), help="output pptx path")
    parser.add_argument("--style", default="infographic", choices=sorted(THEMES), help="visual style preset")
    args = parser.parse_args()

    input_path = Path(args.input)
    markdown = input_path.read_text(encoding="utf-8-sig", errors="ignore") if input_path.exists() else source_markdown()
    title, chapters = parse_chapters(markdown)
    if not chapters:
        raise SystemExit("ERROR: no chapters found in thesis markdown.")
    prs = build_presentation(title, chapters, args.style)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)
    print(f"OK: pptx -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
