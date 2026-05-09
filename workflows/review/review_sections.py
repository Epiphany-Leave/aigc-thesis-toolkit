#!/usr/bin/env python3
"""Review generated thesis sections with an OpenAI-compatible API.

The review is intentionally chunked and serial. A full thesis can be long
enough to time out or overload the model, so this script reviews each planned
section file independently and splits oversized chapters into smaller chunks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"


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
            "ERROR: missing API key. Set engines.generation.providers.writer.api_key "
            "in configs/local.yaml or use the configured api_key_env."
        )
    return base, key, model


def chat_completion(base, key, model, messages, temperature=0.1, timeout=240):
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(
            {"model": model, "messages": messages, "temperature": temperature},
            ensure_ascii=False,
        ).encode("utf-8"),
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


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_sections(config):
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    plan_path = WORK / config.get("assembly", {}).get("plan_file", "thesis/section_plan.json")
    plan = read_json(plan_path, {})
    rows = []
    for item in plan.get("sections", []):
        relative = item.get("file")
        if not relative:
            continue
        path = thesis_dir / relative
        if path.exists():
            rows.append((item, path, path.read_text(encoding="utf-8-sig", errors="ignore")))
    return rows


def split_text(text, max_chars):
    if len(text) <= max_chars:
        return [text]
    chunks = []
    current = []
    current_size = 0
    for paragraph in re.split(r"(\n\s*\n)", text):
        if current_size + len(paragraph) > max_chars and current:
            chunks.append("".join(current).strip())
            current = []
            current_size = 0
        current.append(paragraph)
        current_size += len(paragraph)
    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def build_prompt(item, chunk, chunk_index, chunk_total, dimensions):
    title = item.get("chapter_title") or item.get("title") or item.get("id")
    subsection = item.get("subsection_title")
    dimension_text = "\n".join(
        f"- {name}（权重 {value.get('weight', 0)}）：{value.get('prompt', '')}"
        for name, value in dimensions.items()
    )
    return [
        {
            "role": "system",
            "content": (
                "你是毕业论文审阅助手。只做审阅，不重写正文。"
                "输出必须简洁、可执行，重点指出问题、位置、原因和修改建议。"
                "如果没有明显问题，说明该部分暂未发现高风险问题。"
            ),
        },
        {
            "role": "user",
            "content": f"""请审阅以下论文片段。

章节：{title}
小节：{subsection or "（整章）"}
分块：{chunk_index}/{chunk_total}

审阅维度：
{dimension_text}

请按以下格式输出：
## 结论
- 通过 / 需要修改 / 高风险

## 主要问题
- 问题：...
  位置：...
  建议：...

## 格式与导出风险
- ...

## 需要人工核查
- ...

论文片段：
{chunk}
""",
        },
    ]


def write_report(path, sections):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(sections).strip() + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="只审阅指定 section id 或文件路径")
    parser.add_argument("--max-chars", type=int, default=None, help="单个 review 请求的最大字符数")
    parser.add_argument("--sleep", type=float, default=None, help="每个 review 请求后的等待秒数")
    args = parser.parse_args()

    config = load_config()
    review_config = config.get("review", {})
    dimensions = review_config.get("dimensions", {})
    max_chars = args.max_chars or int(review_config.get("max_chars_per_request", 12000) or 12000)
    sleep_seconds = args.sleep if args.sleep is not None else float(review_config.get("sleep_seconds", 2) or 0)
    timeout = int(review_config.get("request_timeout_seconds", 240) or 240)
    report_path = WORK / review_config.get("output_report", "output/review_results.md")
    log_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis") / "logs"
    log_path = log_dir / f"review_{dt.datetime.now():%Y%m%d_%H%M%S}.md"
    base, key, model = api_config(config)

    rows = load_sections(config)
    if args.only:
        rows = [
            row for row in rows
            if row[0].get("id") == args.only or row[0].get("file") == args.only
        ]
    if not rows:
        raise SystemExit("ERROR: no generated section files found. Run generation first.")

    report_parts = [
        "# 论文 Review 结果",
        f"- 时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 模型：{model}",
        f"- 策略：按章节串行审阅，超过 {max_chars} 字符自动切块，避免一次性审阅整篇导致 API 卡死。",
        "- 产物：本脚本生成 review 报告与日志；workflow.py review 会在审阅完成后重新构建 output/thesis.docx。",
    ]

    for item, path, content in rows:
        chunks = split_text(content, max_chars)
        title = item.get("chapter_title") or item.get("title") or item.get("id")
        print(f"REVIEW: {item.get('id')} ({len(chunks)} chunk)")
        report_parts.append(f"\n# {title}")
        report_parts.append(f"- 文件：{path.relative_to(WORK).as_posix()}")
        for index, chunk in enumerate(chunks, start=1):
            print(f"REVIEW CHUNK: {item.get('id')} {index}/{len(chunks)}")
            messages = build_prompt(item, chunk, index, len(chunks), dimensions)
            result = chat_completion(base, key, model, messages, timeout=timeout)
            report_parts.append(f"\n## 分块 {index}/{len(chunks)}")
            report_parts.append(result)
            if sleep_seconds:
                time.sleep(sleep_seconds)

    write_report(report_path, report_parts)
    write_report(log_path, report_parts)
    print(f"OK: review report -> {report_path}")
    print(f"OK: review log -> {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
