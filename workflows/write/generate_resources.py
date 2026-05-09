#!/usr/bin/env python3
"""Generate user_data/resources.md by scanning user_data with an OpenAI-compatible API."""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".bib", ".tex", ".json", ".yaml", ".yml", ".log"}


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
            sample = read_text_sample(path)
            entries.append(f"## {relative}\n类型：文本；大小：{size} bytes\n\n{sample}")
        else:
            entries.append(f"## {relative}\n类型：二进制/Office/PDF/图片等；大小：{size} bytes\n")

    if not entries:
        return "user_data 目录为空。"
    return "\n\n".join(entries)[:70000]


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
4. 对二进制、Office、PDF、图片文件，只能根据文件名和路径判断用途，不要声称已读取其中内容。
5. 如果资料不足，明确写出缺口，不要补造参数、实验或结论。
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
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing user_data/resources.md")
    args = parser.parse_args()

    config = load_config()
    user_data_dir = WORK / config.get("paths", {}).get("user_data_dir", "user_data")
    output_path = user_data_dir / "resources.md"
    if output_path.exists() and not args.overwrite:
        print(f"SKIP: exists: {output_path}. Use --overwrite to refresh.")
        return 0

    user_data_dir.mkdir(parents=True, exist_ok=True)
    inventory = scan_user_data(user_data_dir)
    base, key, model = api_config(config)
    timeout = int(config.get("engines", {}).get("generation", {}).get("batch", {}).get("request_timeout_seconds", 180))
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
