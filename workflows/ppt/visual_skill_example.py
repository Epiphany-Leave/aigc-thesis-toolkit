#!/usr/bin/env python3
"""Example PPT visual skill.

This script demonstrates the runtime contract used by generate_ppt.py:
- read JSON from stdin
- inspect slide.visual_type / slide.diagram / slide.visual
- return JSON with either {"type": "image", "path": "..."} or
  {"type": "ppt_shapes", "elements": [...]}

It is intentionally small and dependency-free.  Replace the configured command
with a Claude Code skill wrapper or another renderer when one is available.
"""

from __future__ import annotations

import json
import sys


def labels_from(payload: dict) -> list[str]:
    slide = payload.get("slide", {})
    labels = slide.get("diagram") or slide.get("bullets") or []
    if isinstance(labels, str):
        labels = [item.strip() for item in labels.replace("，", ",").replace("、", ",").split(",") if item.strip()]
    labels = [str(item).strip()[:18] for item in labels if str(item).strip()]
    return labels[:5] or ["问题", "方案", "实现", "验证"]


def architecture(labels: list[str], theme: dict) -> list[dict]:
    labels = (labels + ["输入", "处理", "输出"])[:4]
    elements = [
        {"type": "text", "x": 0.1, "y": 0.0, "w": 2.85, "h": 0.25, "text": "Skill 架构图", "size": 10, "bold": True, "align": "center", "color": theme.get("accent", "#2f4858")},
    ]
    for index, label in enumerate(labels):
        y = 0.45 + index * 0.62
        elements.append({"type": "box", "x": 0.36, "y": y, "w": 2.25, "h": 0.38, "text": label, "fill": theme.get("panel2", "#e8f1f8"), "line": theme.get("accent", "#2f4858"), "size": 9})
        if index < len(labels) - 1:
            elements.append({"type": "arrow", "x": 1.5, "y": y + 0.4, "x2": 1.5, "y2": y + 0.56})
    return elements


def process(labels: list[str], theme: dict) -> list[dict]:
    elements = []
    for index, label in enumerate(labels[:4]):
        y = 0.45 + index * 0.68
        elements.append({"type": "circle", "x": 0.12, "y": y + 0.04, "w": 0.28, "h": 0.28, "text": str(index + 1), "fill": theme.get("accent2", "#009688"), "line": theme.get("accent2", "#009688"), "color": "#ffffff", "size": 8})
        elements.append({"type": "box", "x": 0.5, "y": y, "w": 2.35, "h": 0.38, "text": label, "fill": theme.get("panel2", "#ebf7ff"), "line": theme.get("accent", "#1976d2"), "size": 9})
    return elements


def compare(labels: list[str], theme: dict) -> list[dict]:
    elements = []
    for index, label in enumerate(labels[:4]):
        y = 0.35 + index * 0.6
        elements.append({"type": "text", "x": 0.05, "y": y, "w": 2.7, "h": 0.22, "text": label, "size": 9, "bold": True, "color": theme.get("text", "#1f2937")})
        elements.append({"type": "bar", "x": 0.08, "y": y + 0.3, "w": 2.55 - index * 0.3, "h": 0.12, "fill": theme.get("accent2" if index % 2 else "accent", "#1976d2")})
    return elements


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    slide = payload.get("slide", {})
    theme = payload.get("theme", {})
    labels = labels_from(payload)
    visual_type = str(slide.get("visual_type") or slide.get("kind") or "").lower()
    if "arch" in visual_type or "架构" in visual_type:
        elements = architecture(labels, theme)
    elif "compare" in visual_type or "result" in visual_type or "对比" in visual_type:
        elements = compare(labels, theme)
    else:
        elements = process(labels, theme)
    print(json.dumps({"type": "ppt_shapes", "elements": elements}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
