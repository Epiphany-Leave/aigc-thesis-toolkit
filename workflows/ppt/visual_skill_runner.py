#!/usr/bin/env python3
"""AI visual skill runner for the PPT workflow.

The runner is a real runtime adapter:
- read the slide visual contract from stdin
- call the existing OpenAI-compatible API configured in configs/local.yaml
- ask the model for semantic diagram content, not freeform coordinates
- map that semantic content to stable PPT shape elements

It intentionally returns editable PPT shapes instead of a bitmap by default.
That keeps diagrams easy to revise in PowerPoint and avoids extra image
conversion dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"


def clean_text(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", str(text))
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
    visual = config.get("ppt", {}).get("visual_skill", {})
    base = (
        visual.get("api_base")
        or provider.get("api_base")
        or os.environ.get(provider.get("api_base_env", "OPENAI_BASE_URL"))
        or "https://api.openai.com/v1"
    ).rstrip("/")
    key = (
        visual.get("api_key")
        or provider.get("api_key")
        or os.environ.get(provider.get("api_key_env", "OPENAI_API_KEY"), "")
    )
    model = (
        visual.get("model")
        or provider.get("model")
        or os.environ.get(provider.get("model_env", "OPENAI_MODEL"), "gpt-4o-mini")
    )
    timeout = int(visual.get("request_timeout_seconds", generation.get("batch", {}).get("request_timeout_seconds", 600)))
    temperature = float(visual.get("temperature", 0.25))
    return base, key, model, timeout, temperature


def post_chat_completion(base: str, key: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def chat_completion(base: str, key: str, model: str, messages: list[dict], timeout: int, temperature: float) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 3500,
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


def parse_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def slide_labels(payload: dict, limit: int = 5) -> list[str]:
    slide = payload.get("slide", {})
    labels = slide.get("diagram") or slide.get("bullets") or []
    if isinstance(labels, str):
        labels = [item.strip() for item in re.split(r"[,，/、;；\n]", labels) if item.strip()]
    labels = [clean_text(item)[:18] for item in labels if clean_text(item)]
    return labels[:limit] or ["问题", "方案", "实现", "验证"]


def semantic_fallback(payload: dict) -> dict:
    slide = payload.get("slide", {})
    visual_type = str(slide.get("visual_type") or slide.get("kind") or "").lower()
    labels = slide_labels(payload, 5)
    if "arch" in visual_type or "架构" in visual_type:
        return {"diagram_kind": "architecture", "title": "结构关系", "nodes": (labels + ["输入", "处理", "输出"])[:4], "relations": []}
    if "compare" in visual_type or "result" in visual_type or "对比" in visual_type:
        return {"diagram_kind": "compare", "title": "对比要点", "nodes": labels[:4], "relations": []}
    if "summary" in visual_type:
        return {"diagram_kind": "summary", "title": "总结", "nodes": labels[:3], "relations": []}
    return {"diagram_kind": "process", "title": "关键流程", "nodes": labels[:4], "relations": []}


def semantic_nodes(data: dict, payload: dict, limit: int = 5) -> list[str]:
    nodes = data.get("nodes") or data.get("steps") or data.get("items") or []
    if isinstance(nodes, str):
        nodes = [item.strip() for item in re.split(r"[,，/、;；\n]", nodes) if item.strip()]
    if isinstance(nodes, list):
        labels = []
        for item in nodes:
            if isinstance(item, dict):
                label = item.get("label") or item.get("title") or item.get("name") or item.get("text")
            else:
                label = item
            if clean_text(label):
                labels.append(clean_text(label)[:18])
        if labels:
            return labels[:limit]
    return slide_labels(payload, limit)


def semantic_title(data: dict, fallback: str) -> str:
    return clean_text(data.get("title") or data.get("caption") or fallback)[:18]


def safe_float(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def safe_int(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def fallback_elements(payload: dict) -> list[dict]:
    return elements_from_semantic(semantic_fallback(payload), payload)


def architecture_elements(data: dict, payload: dict) -> list[dict]:
    theme = payload.get("theme", {})
    labels = (semantic_nodes(data, payload, 4) + ["输入", "处理", "输出"])[:4]
    elements = [
        {"type": "text", "x": 0.05, "y": 0.0, "w": 2.95, "h": 0.24, "text": semantic_title(data, "结构关系"), "size": 10, "bold": True, "align": "center", "color": theme.get("accent", "#2f4858")},
    ]
    for index, label in enumerate(labels):
        y = 0.44 + index * 0.64
        elements.append({"type": "box", "x": 0.36, "y": y, "w": 2.25, "h": 0.4, "text": label, "fill": theme.get("panel2", "#e8f1f8"), "line": theme.get("accent", "#2f4858"), "size": 9})
        if index < len(labels) - 1:
            elements.append({"type": "arrow", "x": 1.5, "y": y + 0.42, "x2": 1.5, "y2": y + 0.58})
    return elements


def process_elements(data: dict, payload: dict) -> list[dict]:
    theme = payload.get("theme", {})
    labels = semantic_nodes(data, payload, 4)
    elements = []
    for index, label in enumerate(labels):
        y = 0.45 + index * 0.68
        elements.append({"type": "circle", "x": 0.12, "y": y + 0.04, "w": 0.28, "h": 0.28, "text": str(index + 1), "fill": theme.get("accent2", "#009688"), "line": theme.get("accent2", "#009688"), "color": "#ffffff", "size": 8})
        elements.append({"type": "box", "x": 0.5, "y": y, "w": 2.35, "h": 0.38, "text": label, "fill": theme.get("panel2", "#ebf7ff"), "line": theme.get("accent", "#1976d2"), "size": 9})
    return elements


def compare_elements(data: dict, payload: dict) -> list[dict]:
    theme = payload.get("theme", {})
    labels = semantic_nodes(data, payload, 4)
    elements = [{"type": "text", "x": 0.05, "y": 0.02, "w": 2.9, "h": 0.24, "text": semantic_title(data, "对比概览"), "size": 10, "bold": True, "align": "center", "color": theme.get("accent", "#1976d2")}]
    for index, label in enumerate(labels[:4]):
        y = 0.45 + index * 0.56
        elements.append({"type": "text", "x": 0.1, "y": y, "w": 2.5, "h": 0.2, "text": label, "size": 8, "bold": True, "color": theme.get("text", "#1f2937")})
        elements.append({"type": "bar", "x": 0.12, "y": y + 0.27, "w": 2.45 - index * 0.24, "h": 0.12, "fill": theme.get("accent2" if index % 2 else "accent", "#1976d2")})
    return elements


def summary_elements(data: dict, payload: dict) -> list[dict]:
    theme = payload.get("theme", {})
    labels = semantic_nodes(data, payload, 3)[:3]
    elements = [{"type": "text", "x": 0.05, "y": 0.02, "w": 2.9, "h": 0.24, "text": semantic_title(data, "核心结论"), "size": 10, "bold": True, "align": "center", "color": theme.get("accent", "#1976d2")}]
    for index, label in enumerate(labels):
        x = 0.2 + index * 0.92
        elements.append({"type": "box", "x": x, "y": 1.15, "w": 0.75, "h": 0.75, "text": label, "fill": theme.get("panel2", "#ebf7ff"), "line": theme.get("accent", "#1976d2"), "size": 8})
    return elements


def elements_from_semantic(data: dict, payload: dict) -> list[dict]:
    kind = str(data.get("diagram_kind") or data.get("kind") or payload.get("slide", {}).get("visual_type") or "").lower()
    if "arch" in kind or "架构" in kind:
        elements = architecture_elements(data, payload)
    elif "compare" in kind or "result" in kind or "对比" in kind:
        elements = compare_elements(data, payload)
    elif "summary" in kind or "总结" in kind:
        elements = summary_elements(data, payload)
    else:
        elements = process_elements(data, payload)
    return elements[:14]


def clamp_element(element: dict, theme: dict) -> dict:
    kind = str(element.get("type") or "box").lower()
    if kind not in {"box", "circle", "oval", "text", "arrow", "bar"}:
        kind = "box"
    x = max(0.0, min(2.9, safe_float(element.get("x", 0.2), 0.2)))
    y = max(0.0, min(3.3, safe_float(element.get("y", 0.2), 0.2)))
    w = max(0.08, min(3.0 - x, safe_float(element.get("w", element.get("width", 1.0)), 1.0)))
    h = max(0.08, min(3.45 - y, safe_float(element.get("h", element.get("height", 0.35)), 0.35)))
    safe = {
        "type": kind,
        "x": round(x, 3),
        "y": round(y, 3),
        "w": round(w, 3),
        "h": round(h, 3),
        "text": clean_text(element.get("text", ""))[:24],
        "fill": str(element.get("fill") or theme.get("panel2") or "#ebf7ff"),
        "line": str(element.get("line") or theme.get("accent") or "#1976d2"),
        "color": str(element.get("color") or theme.get("text") or "#1f2937"),
        "size": safe_int(element.get("size", 9), 9),
        "bold": bool(element.get("bold", True)),
    }
    if kind == "arrow":
        safe["x2"] = round(max(0.0, min(3.0, safe_float(element.get("x2", element.get("to_x", x + 0.3)), x + 0.3))), 3)
        safe["y2"] = round(max(0.0, min(3.45, safe_float(element.get("y2", element.get("to_y", y + 0.3)), y + 0.3))), 3)
    if element.get("align"):
        safe["align"] = str(element.get("align"))
    return safe


def normalize_output(data: dict, payload: dict) -> dict:
    theme = payload.get("theme", {})
    if not isinstance(data, dict):
        data = semantic_fallback(payload)
    if isinstance(data.get("elements"), list):
        elements = data["elements"]
    else:
        elements = elements_from_semantic(data, payload)
    elements = [clamp_element(item, theme) for item in elements if isinstance(item, dict)][:18]
    return {"type": "ppt_shapes", "elements": elements or fallback_elements(payload)}


def build_messages(payload: dict) -> list[dict]:
    slide = payload.get("slide", {})
    theme = payload.get("theme", {})
    reference_style = payload.get("reference_style", {})
    system = (
        "你是 PPT 图解内容设计师。根据输入的答辩页信息，生成图解语义，不要生成坐标。"
        "只能返回严格 JSON，不要 Markdown。不要虚构论文没有的数据。"
    )
    user = {
        "task": "为一页毕业论文答辩 PPT 设计右侧图解内容。",
        "contract": "只返回 {diagram_kind,title,nodes,relations,highlight}",
        "diagram_kind_options": ["architecture", "process", "compare", "summary"],
        "semantic_requirements": [
            "nodes 3-5 个，每个节点不超过 10 个汉字。",
            "relations 可选，只写真实关系，不要编造数值。",
            "highlight 是一句 18 字以内的图解结论。",
            "不要生成 x/y/w/h 坐标，布局由程序负责。"
        ],
        "slide": slide,
        "theme": theme,
        "reference_style": {
            "visual_side": reference_style.get("visual_side"),
            "palette": reference_style.get("palette", [])[:6],
            "text_anchor_x": reference_style.get("text_anchor_x"),
            "media_anchor_x": reference_style.get("media_anchor_x"),
            "sample_count": reference_style.get("count", 0),
            "privacy_note": "参考 PPT 只提供布局/色彩统计，不包含原文字和图片内容。",
        },
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    config = load_config()
    base, key, model, timeout, temperature = api_config(config)
    if not key:
        print(json.dumps({"type": "ppt_shapes", "elements": fallback_elements(payload)}, ensure_ascii=False))
        return 0
    try:
        content = chat_completion(base, key, model, build_messages(payload), timeout, temperature)
        data = parse_json_object(content)
    except (json.JSONDecodeError, KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(json.dumps({"type": "ppt_shapes", "elements": fallback_elements(payload), "warning": str(exc)}, ensure_ascii=False))
        return 0
    print(json.dumps(normalize_output(data, payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
