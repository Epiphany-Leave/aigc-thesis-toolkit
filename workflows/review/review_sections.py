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


def read_text(path):
    return path.read_text(encoding="utf-8-sig", errors="ignore") if path.exists() else ""


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


def strip_markdown_fence(text):
    text = text.strip()
    fence = re.match(r"^```(?:markdown|md)?\s*(.*?)\s*```$", text, flags=re.S | re.I)
    return fence.group(1).strip() if fence else text


def build_revision_prompt(config, item, original, review_result, chunk_index, chunk_total):
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    user_data_dir = WORK / config.get("paths", {}).get("user_data_dir", "user_data")
    style = read_text(thesis_dir / "style.md")
    outline = read_text(thesis_dir / "outline.md")
    resources = read_text(user_data_dir / "resources.md")
    title = item.get("chapter_title") or item.get("title") or item.get("id")
    subsection = item.get("subsection_title")
    return [
        {
            "role": "system",
            "content": (
                "你是毕业论文自动修订助手。你必须直接输出修订后的 Markdown 正文，不输出解释、建议或审稿报告。"
                "优先保证论文质量、论证完整、格式稳定、与资料一致。不要为了省 token 压缩必要内容。"
                "不得编造资料中没有的数据、实验结果或文献。资料不足时使用保守表述或 TODO。"
            ),
        },
        {
            "role": "user",
            "content": f"""请根据 review 结果直接修订下面的论文片段。

论文题目：{config.get('project', {}).get('title', '')}
章节：{title}
小节：{subsection or "（整章）"}
分块：{chunk_index}/{chunk_total}

写作规范：
{style}

论文大纲：
{outline}

个人资料索引：
{resources}

Review 结果：
{review_result}

原论文片段：
{original}

修订要求：
1. 只输出修订后的 Markdown 正文，不要输出“修改说明”“以下是”等解释。
2. 保留原片段应有的标题层级，不要新增其他章节内容。
3. 充分修复 review 指出的问题，并主动优化单调、空泛、AI 痕迹明显的表达。
4. 保留并规范图、表、公式占位；公式编号必须单独占一行，不要写进 $$...$$。
5. 表格必须为标准 Markdown 管道表格，表题单独一行，表题和表格之间空一行。
6. 正文不要使用 Markdown 加粗或斜体。
7. 不要使用“1. ”这类 Markdown 有序列表，确需分点时使用“（1）”“（2）”，编号前不要有空格。
8. 禁止输出代码块、程序源码或 ``` 围栏。
""",
        },
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="只审阅指定 section id 或文件路径")
    parser.add_argument("--max-chars", type=int, default=None, help="单个 review 请求的最大字符数")
    parser.add_argument("--sleep", type=float, default=None, help="每个 review 请求后的等待秒数")
    parser.add_argument("--apply", dest="apply_revision", action="store_true", help="直接改写 thesis 中的章节文件")
    parser.add_argument("--no-apply", dest="apply_revision", action="store_false", help="只生成 review 报告，不改写章节")
    parser.set_defaults(apply_revision=None)
    args = parser.parse_args()

    config = load_config()
    review_config = config.get("review", {})
    dimensions = review_config.get("dimensions", {})
    max_chars = args.max_chars or int(review_config.get("max_chars_per_request", 12000) or 12000)
    sleep_seconds = args.sleep if args.sleep is not None else float(review_config.get("sleep_seconds", 2) or 0)
    timeout = int(review_config.get("request_timeout_seconds", 240) or 240)
    apply_revision = (
        bool(review_config.get("apply_revision", True))
        if args.apply_revision is None
        else args.apply_revision
    )
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

    chunk_rows = []
    for item, path, content in rows:
        chunks = split_text(content, max_chars)
        for index, chunk in enumerate(chunks, start=1):
            chunk_rows.append((item, path, content, chunks, index, chunk))

    print(f"REVIEW TOTAL: {len(chunk_rows)}")
    report_parts = [
        "# 论文 Review 结果",
        f"- 时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 模型：{model}",
        f"- 策略：按章节串行审阅，超过 {max_chars} 字符自动切块，避免一次性审阅整篇导致 API 卡死。",
        f"- 修订模式：{'直接改写 thesis/sections 并重建 Word' if apply_revision else '只生成建议报告'}",
        "- 产物：本脚本生成 review 报告与日志；workflow.py review 会在审阅完成后重新构建 output/thesis.docx。",
    ]

    processed = 0
    for item, path, content in rows:
        chunks = split_text(content, max_chars)
        title = item.get("chapter_title") or item.get("title") or item.get("id")
        print(f"REVIEW: {item.get('id')} ({len(chunks)} chunk)")
        report_parts.append(f"\n# {title}")
        report_parts.append(f"- 文件：{path.relative_to(WORK).as_posix()}")
        revised_chunks = []
        for index, chunk in enumerate(chunks, start=1):
            processed += 1
            print(f"REVIEW PROGRESS: {processed}/{len(chunk_rows)}")
            print(f"REVIEW CHUNK: {item.get('id')} {index}/{len(chunks)}")
            messages = build_prompt(item, chunk, index, len(chunks), dimensions)
            result = chat_completion(base, key, model, messages, timeout=timeout)
            report_parts.append(f"\n## 分块 {index}/{len(chunks)}")
            report_parts.append(result)
            if apply_revision:
                print(f"REVISE CHUNK: {item.get('id')} {index}/{len(chunks)}")
                revised = chat_completion(
                    base,
                    key,
                    model,
                    build_revision_prompt(config, item, chunk, result, index, len(chunks)),
                    temperature=0.2,
                    timeout=timeout,
                )
                revised_chunks.append(strip_markdown_fence(revised))
            if sleep_seconds:
                time.sleep(sleep_seconds)
        if apply_revision and revised_chunks:
            path.write_text("\n\n".join(revised_chunks).strip() + "\n", encoding="utf-8")
            print(f"OK: revised {path}")

    write_report(report_path, report_parts)
    write_report(log_path, report_parts)
    print(f"OK: review report -> {report_path}")
    print(f"OK: review log -> {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
