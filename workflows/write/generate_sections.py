#!/usr/bin/env python3
"""Generate thesis sections with an OpenAI-compatible Chat Completions API."""

import argparse
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"
PAUSE_FILE = WORK / "thesis" / "pause.flag"


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


def read_text(path):
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def chat_completion(base, key, model, messages, temperature=0.3, timeout=180):
    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"ERROR: API request failed: {exc.code}\n{detail}") from exc
    return data["choices"][0]["message"]["content"].strip()


def build_prompt(config, section, existing_tail):
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    user_data_dir = WORK / config.get("paths", {}).get("user_data_dir", "user_data")
    style = read_text(thesis_dir / "style.md")
    outline = read_text(thesis_dir / "outline.md")
    resources = read_text(user_data_dir / "resources.md")
    chapter_title = section.get("chapter_title") or section.get("title", "")
    subsection_title = section.get("subsection_title") or section.get("title", "")
    subsections = section.get("subsections") or []
    is_chapter_unit = bool(subsections) or not subsection_title
    unit_name = "完整章节" if is_chapter_unit else "论文小节"
    subsection_lines = "\n".join(f"- {title}" for title in subsections) if subsections else "（无）"
    heading_rule = (
        "当前写作单元是完整章节：主标题必须用 # 章节标题，章内小节用 ##，小节下的条目用 ###，必须覆盖下方小节清单。"
        if is_chapter_unit
        else "当前写作单元是小节：主标题用 ## 当前小节标题，不要输出所属章节的 # 标题。"
    )

    return [
        {
            "role": "system",
            "content": (
                "你是严谨的本科毕业论文写作助手。只输出当前写作单元的 Markdown 正文，不解释过程。"
                "优先保证论文质量、上下文一致性、推导完整性和格式稳定性；不要为了省 token 压缩必要论证。"
                "保持学术论文风格、术语统一、逻辑连续。不要编造数据、文献或实验结果。"
                "如果资料不足，用保守表述并保留 TODO 标记。"
            ),
        },
        {
            "role": "user",
            "content": f"""请为以下{unit_name}生成 Markdown 内容。

论文题目：{config.get('project', {}).get('title', '')}

当前写作单元：
- 所属章节：{chapter_title}
- 当前小节：{subsection_title}
- 章节内小节清单：
{subsection_lines}
- 输出文件：{section['file']}

写作规范：
{style}

论文大纲：
{outline}

个人资料索引：
{resources}

前文末尾参考：
{existing_tail}

硬性要求：
1. 只写当前写作单元，不补写其他章节。
2. 使用 Markdown 标题；{heading_rule}
3. 公式必须使用独立 display math，编号必须单独占一行，格式如下：
   $$
   公式内容
   $$
   (X-Y)
   不要把编号写进 $$...$$ 内部，不要使用 \\tag{{}}。
4. 公式宁可少而准确，也不要生成不确定或明显错误的复杂公式；每个公式前后必须有必要的变量说明和物理含义解释。
5. 暂时不要插入真实图片、Markdown 图片语法或 HTML img。需要插图的位置只保留占位、图题和说明，格式如下：
   👉【此处插入图X-Y 图题】
   图X-Y 图题
   说明：这里描述图片应包含的内容、来源或绘制要求。
6. 表题使用“表X-Y 标题”。引用图、表、公式、文献时使用自然中文表述，例如“如式(X-Y)所示”“如图X-Y所示”，不要手写 Markdown 链接。
7. 正文不要使用 Markdown 加粗或斜体，不要输出 **加粗**、__加粗__、*斜体* 这类格式。
8. 不要大量使用列表。确需分点时使用中文括号编号，例如“（1）……”“（2）……”，不要使用 Markdown 有序列表“1. ”。
9. 总字数目标不低于 25000 字；按章生成时每章应充分展开，避免短小提纲化。
10. 不要用代码块包裹整篇输出。
""",
        },
    ]


def plan_path(config):
    return WORK / config.get("assembly", {}).get("plan_file", "thesis/section_plan.json")


def load_plan(config):
    path = plan_path(config)
    if not path.exists():
        raise SystemExit("ERROR: plan not found. Run: python workflow.py plan")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def next_sections(plan, all_sections=False, only=None):
    sections = plan.get("sections", [])
    if only:
        return [item for item in sections if item["id"] == only or item["file"] == only]
    if all_sections:
        return [item for item in sections if item.get("status") != "done"]
    for item in sections:
        if item.get("status") != "done":
            return [item]
    return []


def apply_batch_limit(targets, config, cli_limit=None):
    if cli_limit is not None:
        limit = cli_limit
    else:
        limit = config.get("engines", {}).get("generation", {}).get("batch", {}).get("max_sections_per_run", 1)
    if limit is None or limit <= 0:
        return targets
    return targets[:limit]


def pause_requested():
    return PAUSE_FILE.exists()


def update_plan_status(config, section_id, status):
    path = plan_path(config)
    plan = json.loads(path.read_text(encoding="utf-8-sig"))
    now = datetime.datetime.now().isoformat()
    for item in plan.get("sections", []):
        if item["id"] == section_id:
            item["status"] = status
            item["last_updated"] = now
    write_json(path, plan)


def update_state(config, section_id, section_file, status):
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    state_path = thesis_dir / "state.json"
    if not state_path.exists():
        return

    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    chapter = state.setdefault("chapters", {}).setdefault(section_id, {})
    chapter["file"] = section_file
    chapter["status"] = status
    chapter["last_updated"] = datetime.datetime.now().isoformat()
    write_json(state_path, state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="generate every pending planned subsection")
    parser.add_argument("--only", default=None, help="generate one subsection id or file")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--sleep", type=float, default=None, help="seconds between API calls")
    parser.add_argument("--max-sections", type=int, default=None, help="maximum subsections to generate in this run")
    args = parser.parse_args()

    config = load_config()
    base, key, model = api_config(config)
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    plan = load_plan(config)
    targets = apply_batch_limit(next_sections(plan, all_sections=args.all, only=args.only), config, args.max_sections)
    if not targets:
        print("OK: no pending sections")
        return 0

    batch = config.get("engines", {}).get("generation", {}).get("batch", {})
    sleep_seconds = args.sleep if args.sleep is not None else float(batch.get("sleep_seconds", 0.0) or 0.0)
    timeout = int(batch.get("request_timeout_seconds", 180) or 180)
    existing_tail = ""
    for section in targets:
        if pause_requested():
            print(f"PAUSED: found {PAUSE_FILE}. Remove it or run python workflow.py resume to continue.")
            return 0

        path = thesis_dir / section["file"]
        if path.exists() and path.read_text(encoding="utf-8-sig").strip() and not args.overwrite:
            print(f"SKIP: exists: {path}")
            update_plan_status(config, section["id"], "done")
            update_state(config, section["id"], section["file"], "done")
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        update_plan_status(config, section["id"], "in_progress")
        update_state(config, section["id"], section["file"], "in_progress")
        messages = build_prompt(config, section, existing_tail)
        content = chat_completion(base, key, model, messages, timeout=timeout)
        path.write_text(content.strip() + "\n", encoding="utf-8")
        update_plan_status(config, section["id"], "done")
        update_state(config, section["id"], section["file"], "done")
        max_tail = int(batch.get("max_context_tail_chars", 8000) or 8000)
        existing_tail = content[-max_tail:]
        print(f"OK: generated {path}")
        if sleep_seconds:
            time.sleep(sleep_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
