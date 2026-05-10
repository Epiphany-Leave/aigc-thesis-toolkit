#!/usr/bin/env python3
"""从 user_data 中提取资料摘要，并调用 OpenAI 兼容接口生成论文大纲。"""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import yaml


工程根目录 = Path(__file__).resolve().parents[2]
配置文件 = 工程根目录 / "configs" / "default.yaml"
本地配置文件 = 工程根目录 / "configs" / "local.yaml"
可读取后缀 = {".md", ".txt", ".csv", ".bib", ".tex", ".json", ".yaml", ".yml"}


def 读取配置():
    配置 = yaml.safe_load(配置文件.read_text(encoding="utf-8")) or {}
    if 本地配置文件.exists():
        配置 = 深度合并(配置, yaml.safe_load(本地配置文件.read_text(encoding="utf-8")) or {})
    return 配置


def 深度合并(基础, 覆盖):
    if not isinstance(基础, dict) or not isinstance(覆盖, dict):
        return 覆盖
    结果 = dict(基础)
    for 键, 值 in 覆盖.items():
        结果[键] = 深度合并(结果.get(键), 值) if 键 in 结果 else 值
    return 结果


def 接口配置(配置):
    提供方 = 配置.get("engines", {}).get("generation", {}).get("providers", {}).get("writer", {})
    地址 = (
        提供方.get("api_base")
        or os.environ.get(提供方.get("api_base_env", "OPENAI_BASE_URL"))
        or "https://api.openai.com/v1"
    ).rstrip("/")
    密钥 = 提供方.get("api_key") or os.environ.get(提供方.get("api_key_env", "OPENAI_API_KEY"), "")
    模型 = 提供方.get("model") or os.environ.get(提供方.get("model_env", "OPENAI_MODEL"), "gpt-4o-mini")
    if not 密钥:
        raise SystemExit("错误：请在 configs/default.yaml 的 engines.generation.providers.writer.api_key 中配置 API Key，或使用配置的环境变量。")
    return 地址, 密钥, 模型


def 调用模型(地址, 密钥, 模型, 消息):
    配置 = 读取配置()
    超时 = int(配置.get("engines", {}).get("generation", {}).get("batch", {}).get("request_timeout_seconds", 180) or 180)
    请求 = urllib.request.Request(
        f"{地址}/chat/completions",
        data=json.dumps({"model": 模型, "messages": 消息, "temperature": 0.2}, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {密钥}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(请求, timeout=超时) as 响应:
            数据 = json.loads(响应.read().decode("utf-8"))
    except urllib.error.HTTPError as 异常:
        详情 = 异常.read().decode("utf-8", errors="replace")
        raise SystemExit(f"错误：API 请求失败：{异常.code}\n{详情}") from 异常
    return 数据["choices"][0]["message"]["content"].strip()


def 读取文本片段(路径, 字数上限=12000):
    try:
        内容 = 路径.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return ""
    return 内容[:字数上限]


def 扫描资料(资料目录):
    资源索引 = 资料目录 / "resources.md"
    if 资源索引.exists():
        内容 = 读取文本片段(资源索引, 60000)
        if 内容.strip():
            return f"## 文件：resources.md\n\n{内容}"

    条目 = []
    if not 资料目录.exists():
        return "user_data 目录不存在。"

    for 路径 in sorted(资料目录.rglob("*")):
        if 路径.is_dir():
            continue
        相对路径 = 路径.relative_to(资料目录).as_posix()
        if 路径.suffix.lower() in 可读取后缀:
            内容 = 读取文本片段(路径)
            条目.append(f"## 文件：{相对路径}\n\n{内容}")
        else:
            条目.append(f"## 文件：{相对路径}\n\n（二进制或 Office/PDF 文件，仅记录文件名供判断资料类型）")

    if not 条目:
        return "user_data 目录为空。"
    return "\n\n".join(条目)[:60000]


def 构造提示词(配置, 资料摘要, 写作规范):
    题目 = 配置.get("project", {}).get("title", "未命名论文")
    return [
        {
            "role": "system",
            "content": (
                "你是本科毕业论文大纲规划助手。你需要根据用户资料生成可执行论文大纲。"
                "只输出 Markdown，不解释过程，不输出代码块。"
            ),
        },
        {
            "role": "user",
            "content": f"""请根据资料生成 thesis/outline.md。

论文题目：{题目}

写作规范：
{写作规范}

资料摘要：
{资料摘要}

输出要求：
1. 一级标题为“# 论文大纲”。
2. 每个需要生成正文的章节必须使用二级标题“##”。
3. 章节下面使用三级标题“###”列出节、条的写作结构。
4. 开头和结尾顺序必须稳定：开头为“摘要”“绪论”，结尾为“总结与展望”“参考文献”“致谢”。
5. 中间主体章节不要套固定模板，必须根据 user_data/resources.md 中真实资料生成；例如可以围绕总体方案、机械结构、硬件电路、控制算法、软件流程、系统集成、测试分析等内容灵活安排。
6. 中间主体章节的逻辑顺序应符合本科工科论文习惯：需求/背景之后，先方案与设计，再实现与集成，最后测试与分析；不要把测试放在设计之前，不要把参考文献或致谢插到主体章节之间。
7. 如果资料显示某一类内容很少，不要硬造独立章节；可以合并成更贴合资料的章节。
8. 可包含参考文献、致谢，但它们不会作为正文生成章节。
9. 章节安排要贴合 user_data/resources.md 中真实存在的资料，不要凭空发明实验或数据。
10. 不要输出“第零章”“附录”或与论文无关的章节。

结构约束示例：
## 摘要
## 绪论
### 研究背景与意义
### 国内外研究现状
### 主要研究内容
## （根据资料生成的主体章节一）
### （根据资料生成的小节）
## （根据资料生成的主体章节二）
### （根据资料生成的小节）
## （根据资料生成的主体章节三）
### （根据资料生成的小节）
## 总结与展望
## 参考文献
## 致谢
""",
        },
    ]


def 主函数():
    解析器 = argparse.ArgumentParser()
    解析器.add_argument("--overwrite", action="store_true", help="覆盖已有 thesis/outline.md")
    参数 = 解析器.parse_args()

    配置 = 读取配置()
    论文目录 = 工程根目录 / 配置.get("paths", {}).get("thesis_dir", "thesis")
    资料目录 = 工程根目录 / 配置.get("paths", {}).get("user_data_dir", "user_data")
    大纲路径 = 论文目录 / "outline.md"
    规范路径 = 论文目录 / "style.md"

    if 大纲路径.exists() and not 参数.overwrite:
        print(f"跳过：已存在 {大纲路径}。如需重写，请加 --overwrite。")
        return 0

    论文目录.mkdir(parents=True, exist_ok=True)
    资料摘要 = 扫描资料(资料目录)
    写作规范 = 读取文本片段(规范路径)
    地址, 密钥, 模型 = 接口配置(配置)
    大纲内容 = 调用模型(地址, 密钥, 模型, 构造提示词(配置, 资料摘要, 写作规范))
    大纲路径.write_text(大纲内容.strip() + "\n", encoding="utf-8")
    print(f"完成：已生成 {大纲路径}")
    return 0


if __name__ == "__main__":
    raise SystemExit(主函数())
