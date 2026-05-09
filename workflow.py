#!/usr/bin/env python3
"""论文生成与 Word 导出的统一入口。"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


工程根目录 = Path(__file__).resolve().parent
暂停文件 = 工程根目录 / "thesis" / "pause.flag"


def 运行命令(命令):
    print("+ " + " ".join(命令))
    return subprocess.run(命令, cwd=工程根目录, check=False).returncode


def 缺失时写入(路径, 内容):
    if 路径.exists():
        return False
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(内容, encoding="utf-8")
    return True


def 初始化工程(_参数):
    固定目录 = [
        工程根目录 / "thesis" / "sections",
        工程根目录 / "thesis" / "logs",
        工程根目录 / "output",
        工程根目录 / "user_data",
    ]
    for 目录 in 固定目录:
        目录.mkdir(parents=True, exist_ok=True)

    新建文件 = []
    模板文件 = {
        工程根目录 / "thesis" / "style.md": """# 写作与格式规范

- 使用本科毕业论文的正式学术表达。
- 章节内容按照自动生成的 thesis/outline.md 展开。
- 公式使用 LaTeX 块公式。
- 图题使用“图X-Y 标题”。
- 表题使用“表X-Y 标题”。
- 引用图片、表格、公式、文献时不要写无法追踪的占位符。
- 正文不要使用加粗、斜体等 Markdown 强调格式。
- 正文不要使用“1. ”形式的有序列表，必要时使用“（1）”形式并减少列条，编号前不要有空格。
- 正文不要出现代码块或程序源码。
- 表格使用标准 Markdown 管道表格，表题单独放在表格前，表题和表格之间保留空行。
- 正文字数目标不低于 25000 字。
""",
    }

    for 路径, 内容 in 模板文件.items():
        if 缺失时写入(路径, 内容):
            新建文件.append(路径.relative_to(工程根目录).as_posix())

    print("完成：固定目录已准备好。")
    if 新建文件:
        print("新建文件：")
        for 文件 in 新建文件:
            print(f"  {文件}")
    return 0


def 生成大纲(参数):
    规范命令 = [sys.executable, "workflows/write/generate_style.py"]
    退出码 = 运行命令(规范命令)
    if 退出码 != 0:
        return 退出码
    资源命令 = [sys.executable, "workflows/write/generate_resources.py", "--overwrite"]
    退出码 = 运行命令(资源命令)
    if 退出码 != 0:
        return 退出码
    命令 = [sys.executable, "workflows/write/generate_outline.py"]
    if 参数.overwrite:
        命令.append("--overwrite")
    return 运行命令(命令)


def 生成资料索引(参数):
    命令 = [sys.executable, "workflows/write/generate_resources.py"]
    if 参数.overwrite:
        命令.append("--overwrite")
    return 运行命令(命令)


def 生成写作规范(参数):
    命令 = [sys.executable, "workflows/write/generate_style.py"]
    if 参数.overwrite:
        命令.append("--overwrite")
    return 运行命令(命令)


def 生成计划(参数):
    命令 = [sys.executable, "workflows/write/plan_from_outline.py"]
    if 参数.overwrite_state:
        命令.append("--overwrite-state")
    return 运行命令(命令)


def 生成章节(参数):
    命令 = [sys.executable, "workflows/write/generate_sections.py"]
    if 参数.all:
        命令.append("--all")
    if 参数.only:
        命令.extend(["--only", 参数.only])
    if 参数.overwrite:
        命令.append("--overwrite")
    if 参数.sleep:
        命令.extend(["--sleep", str(参数.sleep)])
    if 参数.max_sections is not None:
        命令.extend(["--max-sections", str(参数.max_sections)])
    return 运行命令(命令)


def 构建文档(参数):
    if shutil.which("bash") is None:
        print("错误：未找到 bash。请在 WSL 或 Git Bash 中运行。", file=sys.stderr)
        return 1
    命令 = ["bash", "workflows/build_all.sh"]
    if 参数.no_assemble:
        命令.append("--no-assemble")
    return 运行命令(命令)


def 审阅论文(参数):
    命令 = [sys.executable, "workflows/review/review_sections.py"]
    if 参数.only:
        命令.extend(["--only", 参数.only])
    if 参数.max_chars:
        命令.extend(["--max-chars", str(参数.max_chars)])
    退出码 = 运行命令(命令)
    if 退出码 != 0:
        return 退出码
    print("Review 完成，开始重新构建 Word 文档。")
    return 运行命令([sys.executable, "workflow.py", "build"])


def 清空目录内容(目录):
    目录.mkdir(parents=True, exist_ok=True)
    for 路径 in 目录.iterdir():
        if 路径.name == ".gitkeep":
            continue
        if 路径.is_dir():
            shutil.rmtree(路径)
        else:
            路径.unlink(missing_ok=True)


def 重置工程(参数):
    if not 参数.yes:
        print("此操作会删除 user_data、已生成章节、输出文件、大纲、计划、状态和日志。确认请追加 --yes。")
        return 1

    清空目录内容(工程根目录 / "user_data")
    清空目录内容(工程根目录 / "thesis" / "sections")
    清空目录内容(工程根目录 / "thesis" / "logs")
    清空目录内容(工程根目录 / "output")

    for 路径 in [
        工程根目录 / "thesis" / "outline.md",
        工程根目录 / "thesis" / "section_plan.json",
        工程根目录 / "thesis" / "state.json",
        工程根目录 / "thesis" / "pause.flag",
        工程根目录 / "user_data" / "resources.md",
    ]:
        路径.unlink(missing_ok=True)

    if 参数.reset_style:
        (工程根目录 / "thesis" / "style.md").unlink(missing_ok=True)
        初始化工程(argparse.Namespace())

    print("已重置：生成内容、输出文件、日志和 user_data 已清空。configs/local.yaml 与 API 配置已保留。")
    return 0


def 启动界面(参数):
    命令 = [sys.executable, "workflows/webui/server.py", str(参数.port)]
    return 运行命令(命令)


def 暂停生成(_参数):
    暂停文件.parent.mkdir(parents=True, exist_ok=True)
    暂停文件.write_text("paused\n", encoding="utf-8")
    print("已请求暂停：当前写作单元完成后会停在下一个写作单元开始前。")
    return 0


def 继续生成(_参数):
    if 暂停文件.exists():
        暂停文件.unlink()
        print("已恢复：可以继续生成。")
    else:
        print("当前没有暂停标记。")
    return 0


def 章节全部完成():
    计划路径 = 工程根目录 / "thesis" / "section_plan.json"
    if not 计划路径.exists():
        return False
    计划 = json.loads(计划路径.read_text(encoding="utf-8-sig"))
    章节 = 计划.get("sections", [])
    return bool(章节) and all(项.get("status") == "done" for 项 in 章节)


def 完整流程(参数):
    生成命令 = [sys.executable, "workflow.py", "generate", "--all"]
    if 参数.max_sections is not None:
        生成命令.extend(["--max-sections", str(参数.max_sections)])
    命令列表 = [
        [sys.executable, "workflow.py", "init"],
        [sys.executable, "workflow.py", "outline"],
        [sys.executable, "workflow.py", "plan"],
        生成命令,
    ]
    for 命令 in 命令列表:
        退出码 = 运行命令(命令)
        if 退出码 != 0:
            return 退出码
    if not 章节全部完成():
        if 暂停文件.exists():
            print("生成已暂停；仍有未完成写作单元，暂不导出 Word。运行 python workflow.py resume 后可继续。")
        else:
            print("仍有未完成写作单元，暂不导出 Word。可继续运行 python workflow.py all。")
        return 0
    return 运行命令([sys.executable, "workflow.py", "build"])


def 查看状态(_参数):
    大纲路径 = 工程根目录 / "thesis" / "outline.md"
    计划路径 = 工程根目录 / "thesis" / "section_plan.json"

    if not 大纲路径.exists():
        print("尚未生成论文大纲。运行：python workflow.py outline")
        return 0
    if not 计划路径.exists():
        print("尚未生成章节计划。运行：python workflow.py plan")
        return 0

    计划 = json.loads(计划路径.read_text(encoding="utf-8-sig"))
    章节 = 计划.get("sections", [])
    已完成 = sum(1 for 项 in 章节 if 项.get("status") == "done")
    print(f"章节计划：{计划路径.relative_to(工程根目录).as_posix()}")
    print(f"进度：{已完成}/{len(章节)}")
    print("---")
    for 项 in 章节:
        print(f"[{项.get('status', 'pending')}] {项.get('id')} -> {项.get('file')}")
    return 0


def 主函数():
    解析器 = argparse.ArgumentParser(description="论文生成与 Word 导出的统一入口")
    子命令 = 解析器.add_subparsers(dest="command", required=True)

    初始化 = 子命令.add_parser("init", help="创建固定目录，并补齐 style.md")
    初始化.set_defaults(func=初始化工程)

    资料 = 子命令.add_parser("resources", help="扫描 user_data 并调用 OpenAI 兼容 API 生成 user_data/resources.md")
    资料.add_argument("--overwrite", action="store_true", help="覆盖已有 user_data/resources.md")
    资料.set_defaults(func=生成资料索引)

    规范 = 子命令.add_parser("style", help="扫描 user_data 并调用 OpenAI 兼容 API 生成 thesis/style.md")
    规范.add_argument("--overwrite", action="store_true", help="覆盖已有 thesis/style.md")
    规范.set_defaults(func=生成写作规范)

    大纲 = 子命令.add_parser("outline", help="扫描 user_data 并调用 OpenAI 兼容 API 生成 thesis/outline.md")
    大纲.add_argument("--overwrite", action="store_true", help="覆盖已有 thesis/outline.md")
    大纲.set_defaults(func=生成大纲)

    计划 = 子命令.add_parser("plan", help="根据 thesis/outline.md 生成章节计划")
    计划.add_argument("--overwrite-state", action="store_true", help="同时重写 thesis/state.json")
    计划.set_defaults(func=生成计划)

    章节 = 子命令.add_parser("generate", help="调用 OpenAI 兼容 API 生成小节")
    章节.add_argument("--all", action="store_true", help="生成所有未完成小节")
    章节.add_argument("--only", help="只生成指定小节 id 或小节文件")
    章节.add_argument("--overwrite", action="store_true", help="覆盖已有小节文件")
    章节.add_argument("--sleep", type=float, default=0.0, help="每个小节生成后的等待秒数")
    章节.add_argument("--max-sections", type=int, default=None, help="本次最多生成多少个小节；0 表示不限制")
    章节.set_defaults(func=生成章节)

    构建 = 子命令.add_parser("build", help="合并 Markdown 并导出 Word")
    构建.add_argument("--no-assemble", action="store_true", help="跳过章节合并，只导出已有 output/thesis.md")
    构建.set_defaults(func=构建文档)

    审阅 = 子命令.add_parser("review", help="按章节/分块审阅已生成论文，输出 review 报告")
    审阅.add_argument("--only", help="只审阅指定 section id 或章节文件")
    审阅.add_argument("--max-chars", type=int, default=None, help="单次 review 请求最大字符数")
    审阅.set_defaults(func=审阅论文)

    重置 = 子命令.add_parser("reset", help="清空生成内容、输出文件、日志和 user_data，开始新论文")
    重置.add_argument("--yes", action="store_true", help="确认执行重置")
    重置.add_argument("--reset-style", action="store_true", help="同时重置 thesis/style.md")
    重置.set_defaults(func=重置工程)

    界面 = 子命令.add_parser("ui", help="启动本地 WebUI")
    界面.add_argument("--port", type=int, default=8765, help="WebUI 端口")
    界面.set_defaults(func=启动界面)

    全部 = 子命令.add_parser("all", help="初始化、生成大纲、生成章节、导出 Word")
    全部.add_argument("--max-sections", type=int, default=None, help="本次最多生成多少个小节；默认读取 YAML")
    全部.set_defaults(func=完整流程)

    暂停 = 子命令.add_parser("pause", help="当前小节完成后暂停继续生成")
    暂停.set_defaults(func=暂停生成)

    恢复 = 子命令.add_parser("resume", help="取消暂停标记")
    恢复.set_defaults(func=继续生成)

    状态 = 子命令.add_parser("status", help="查看当前生成进度")
    状态.set_defaults(func=查看状态)

    参数 = 解析器.parse_args()
    return 参数.func(参数)


if __name__ == "__main__":
    raise SystemExit(主函数())
