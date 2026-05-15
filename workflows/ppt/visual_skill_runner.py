#!/usr/bin/env python3
"""AI visual skill runner for the PPT workflow.

The runner is a real runtime adapter:
- read the slide visual contract from stdin
- call the existing OpenAI-compatible API configured in configs/local.yaml
- return PPT shape elements on stdout for generate_ppt.py to insert

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


def fallback_elements(payload: dict) -> list[dict]:
    slide = payload.get("slide", {})
    theme = payload.get("theme", {})
    labels = slide.get("diagram") or slide.get("bullets") or []
    if isinstance(labels, str):
        labels = [item.strip() for item in re.split(r"[,，/、;；\n]", labels) if item.strip()]
    labels = [clean_text(item)[:18] for item in labels if clean_text(item)][:4] or ["问题", "方案", "实现", "验证"]
    visual_type = str(slide.get("visual_type") or slide.get("kind") or "").lower()
    if "arch" in visual_type or "架构" in visual_type:
        labels = (labels + ["输入", "处理", "输出"])[:4]
        elements = [{"type": "text", "x": 0.1, "y": 0.0, "w": 2.85, "h": 0.25, "text": "AI 架构图", "size": 10, "bold": True, "align": "center", "color": theme.get("accent", "#2f4858")}]
        for index, label in enumerate(labels):
            y = 0.45 + index * 0.62
            elements.append({"type": "box", "x": 0.36, "y": y, "w": 2.25, "h": 0.38, "text": label, "fill": theme.get("panel2", "#e8f1f8"), "line": theme.get("accent", "#2f4858"), "size": 9})
            if index < len(labels) - 1:
                elements.append({"type": "arrow", "x": 1.5, "y": y + 0.4, "x2": 1.5, "y2": y + 0.56})
        return elements
    elements = []
    for index, label in enumerate(labels):
        y = 0.45 + index * 0.68
        elements.append({"type": "circle", "x": 0.12, "y": y + 0.04, "w": 0.28, "h": 0.28, "text": str(index + 1), "fill": theme.get("accent2", "#009688"), "line": theme.get("accent2", "#009688"), "color": "#ffffff", "size": 8})
        elements.append({"type": "box", "x": 0.5, "y": y, "w": 2.35, "h": 0.38, "text": label, "fill": theme.get("panel2", "#ebf7ff"), "line": theme.get("accent", "#1976d2"), "size": 9})
    return elements


def clamp_element(element: dict, theme: dict) -> dict:
    kind = str(element.get("type") or "box").lower()
    if kind not in {"box", "circle", "oval", "text", "arrow", "bar"}:
        kind = "box"
    x = max(0.0, min(2.9, float(element.get("x", 0.2))))
    y = max(0.0, min(3.3, float(element.get("y", 0.2))))
    w = max(0.08, min(3.0 - x, float(element.get("w", element.get("width", 1.0)))))
    h = max(0.08, min(3.45 - y, float(element.get("h", element.get("height", 0.35)))))
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
        "size": int(element.get("size", 9)),
        "bold": bool(element.get("bold", True)),
    }
    if kind == "arrow":
        safe["x2"] = round(max(0.0, min(3.0, float(element.get("x2", element.get("to_x", x + 0.3))))), 3)
        safe["y2"] = round(max(0.0, min(3.45, float(element.get("y2", element.get("to_y", y + 0.3))))), 3)
    if element.get("align"):
        safe["align"] = str(element.get("align"))
    return safe


def normalize_output(data: dict, payload: dict) -> dict:
    theme = payload.get("theme", {})
    elements = data.get("elements") if isinstance(data, dict) else None
    if not isinstance(elements, list) or not elements:
        elements = fallback_elements(payload)
    elements = [clamp_element(item, theme) for item in elements if isinstance(item, dict)][:18]
    return {"type": "ppt_shapes", "elements": elements or fallback_elements(payload)}


def build_messages(payload: dict) -> list[dict]:
    slide = payload.get("slide", {})
    theme = payload.get("theme", {})
    system = (
        "你是 PPT 图解 skill runner。根据输入的答辩页信息，生成可编辑 PPT 形状 JSON。"
        "只能返回严格 JSON，不要 Markdown。不要虚构论文没有的数据。"
    )
    user = {
        "task": "为一页毕业论文答辩 PPT 生成右侧图解形状。",
        "contract": "只返回 {type:'ppt_shapes', elements:[...]}",
        "allowed_element_types": ["box", "circle", "oval", "text", "arrow", "bar"],
        "coordinate_system": "x/y/w/h 单位是英寸，相对 3.05 x 3.45 的图解区域左上角；x 0-3.0，y 0-3.45。",
        "shape_requirements": [
            "元素 4-10 个，文字短，适合答辩 PPT。",
            "架构图用 box + arrow 表示层级/流向。",
            "流程图用 circle 编号 + box 表示步骤。",
            "对比/结果图用 text + bar 表示差异，不能编造具体数值。",
            "文字不要超过 18 个汉字。"
        ],
        "slide": slide,
        "theme": theme,
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
