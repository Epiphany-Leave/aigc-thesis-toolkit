# AIGC Thesis Toolkit

AIGC Thesis Toolkit 是一个本地运行的 AI 论文写作工作流。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

![AIGC Thesis Toolkit WebUI](image.png)

它可以把你放入 `user_data/` 的参考资料、学校格式要求、开题/中期报告、参考论文、仿真或实验数据等内容，整理成可追踪的资料索引，并辅助生成论文大纲、章节正文、完整 Markdown 和 Word 文档。
这个项目的目标不是“一键交作业”，而是提供一个更稳定、更可控、更容易续写的 AIGC 论文工作台：你提供真实资料和格式要求，系统默认按章串行生成内容，并保留中间文件、状态和预览，方便你检查、修改和导出。

## 功能亮点

- **本地 WebUI 工作台**：在浏览器里配置 API、上传资料、编辑/导入写作规范、启动生成、暂停/继续、查看进度和实时预览正文。
- **支持 OpenAI 兼容接口**：只要服务兼容 Chat Completions 格式，就可以通过 `api_base`、`api_key`、`model` 接入。
- **自动资料索引**：扫描 `user_data/`，生成 `user_data/resources.md`，让模型知道有哪些可用资料。
- **自动写作规范**：可以从学校模板、任务书、开题报告、论文范例等资料中生成 `thesis/style.md`，也可以手动导入。
- **按章高质量生成**：默认把论文大纲拆成章节任务，一章生成完成后再进入下一章，用更高 token 消耗换取更好的上下文一致性。
- **可暂停、可续写**：生成进度记录在 `thesis/section_plan.json`，已经完成的章节默认不会重复生成。
- **稳定的导出格式**：公式编号会在导出前从公式体中拆出；插图默认保留位置、题注和说明，不直接插入图片。
- **导出 Word**：把生成的小节合并成 `output/thesis.md`，再按 `template/reference.docx` 导出 `output/thesis.docx`。
- **适合上传 GitHub**：API Key、个人资料、生成正文、日志和输出文件默认不会提交。

## 工作流程

```text
user_data/ 个人资料
        -> AI 生成 user_data/resources.md
        -> AI 生成或导入 thesis/style.md
        -> AI 生成 thesis/outline.md
        -> 生成 thesis/section_plan.json
        -> 逐章生成 thesis/sections/
        -> 合并 output/thesis.md
        -> 导出 output/thesis.docx
```

## 快速开始

推荐在 WSL、Linux、macOS 或其他支持 `venv` 的 Python 环境中运行。

```bash
git clone https://github.com/Epiphany-Leave/aigc-thesis-toolkit.git
cd aigc-thesis-toolkit

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python workflow.py init
```

安装并构建新版 WebUI：

```bash
cd workflows/webui/frontend
npm install
npm run build
cd ../../..
```

启动本地服务：

```bash
python workflow.py ui
```

打开浏览器：

```text
http://127.0.0.1:8765
```

如果 `8765` 端口已被占用，程序会自动尝试后续端口，并在终端输出实际地址。

开发 WebUI 时可以开两个终端：

```bash
# 终端 1：启动 Python 后端
python workflow.py ui

# 终端 2：启动 Vite 前端开发服务
cd workflows/webui/frontend
npm run dev
```

开发模式打开：

```text
http://127.0.0.1:5173
```

## WebUI 使用方式

启动 WebUI 后，常规流程都可以在页面里完成：

1. 填写论文题目、API Base、API Key、模型、超时时间和章节间隔。
2. 上传论文相关资料到 `user_data/`，支持选择多个文件，也支持选择整个文件夹；上传完成后页面会提示导入结果。
3. 编辑、导入或自动生成 `thesis/style.md` 写作规范。
4. 点击“开始完整流程”。
5. 在页面右侧查看论文大纲、任务输出和实时论文预览。
6. 需要停下时点击“暂停”，当前章节完成后会停在下一章之前。
7. 生成完成后点击“构建 Word”，得到最终文档。

WebUI 保存的私有配置会写入：

```text
configs/local.yaml
```

这个文件已经被 `.gitignore` 忽略，不会默认上传到 GitHub。

## 应该上传哪些资料

可以把资料放入 `user_data/`，也可以通过 WebUI 上传。

推荐上传：

- 任务书、开题报告、中期报告、学校格式规范
- 参考论文、BibTeX、文献笔记
- 仿真文件、实验数据、CSV/Excel 表格
- 原理图、流程图、实物照片、结果图片
- 学校提供的 Word 模板或往届论文范例

目前文本类文件会被直接抽取片段。PDF、Word、图片等二进制文件会先作为文件名和路径线索使用；如果希望模型读取其中内容，建议先把关键内容整理成 Markdown/TXT 放入 `user_data/`。

WebUI 中的资料列表只显示文件总数、总大小和前若干个文件预览，避免大文件夹上传后刷屏。完整文件仍会保存到 `user_data/`。

## API 配置

最简单的方式是在 WebUI 中填写 API 信息。

如果想手动配置，可以复制示例文件：

```bash
cp configs/local.example.yaml configs/local.yaml
```

然后编辑 `configs/local.yaml`：

```yaml
project:
  title: "你的论文题目"

engines:
  generation:
    granularity: "chapter"
    providers:
      writer:
        api_base: "https://api.openai.com/v1"
        api_key: "你的 API Key"
        model: "gpt-4o-mini"
    batch:
      max_sections_per_run: 0
      sleep_seconds: 3
      request_timeout_seconds: 300
      max_context_tail_chars: 8000
```

说明：

- `engines.generation.granularity: "chapter"` 是默认高质量模式，一次生成一章；如果更想省 token，可以改成 `"subsection"`。
- `max_sections_per_run: 0` 表示 `generate --all` 会连续串行生成所有未完成写作单元。
- 如果想限制单次最多生成 3 个写作单元，可以设为 `3`。
- `sleep_seconds` 是两个写作单元请求之间的等待时间。
- `request_timeout_seconds` 是单次 API 请求超时时间。

## 命令行用法

WebUI 覆盖了常用操作，但所有步骤也可以用命令行运行。

完整流程：

```bash
python workflow.py init
python workflow.py style --overwrite
python workflow.py resources --overwrite
python workflow.py outline
python workflow.py plan
python workflow.py generate --all
python workflow.py build
```

常用命令：

```bash
python workflow.py status                 # 查看进度
python workflow.py generate               # 生成下一个未完成写作单元
python workflow.py generate --all         # 串行生成全部未完成写作单元
python workflow.py generate --all --max-sections 3
python workflow.py pause                  # 当前写作单元完成后暂停
python workflow.py resume                 # 取消暂停
python workflow.py build --no-assemble    # 只导出已有 output/thesis.md
python workflow.py ui --port 8766         # 指定 WebUI 端口
```

## 输出文件

最终结果：

```text
output/thesis.md
output/thesis.docx
output/quality_gate_report.md
```

中间文件：

```text
user_data/resources.md
thesis/outline.md
thesis/section_plan.json
thesis/state.json
thesis/sections/
thesis/logs/
```

这些文件与个人资料或生成内容有关，默认不会提交到版本库。

## 项目结构

```text
aigc-thesis-toolkit/
├── workflow.py                      # CLI 主入口
├── configs/
│   └── default.yaml                 # 默认配置（引擎权重、API、阈值）
│   └── local.example.yaml           # 私有配置示例
├── template/
│   └── reference.docx               # Word 样式模板
├── thesis/                          
│   ├── style.md                     # 写作与格式规范
│   ├── sections/                    # 生成的章节/小节 Markdown
│   └── logs/                        # 运行日志
├── user_data/                       # 输出报告（终端/txt/json/html）
│   └── hc3/                         # 个人资料目录占位说明
├── workflows/
│   ├── write/                       # 资料、规范、大纲、正文生成
│   ├── export_docx/                 # Markdown 到 Word 的导出流程
│   ├── review/                      # 质量检查与审阅流程
│   └── webui/                       # 本地 WebUI 与 Vite 前端
└── output/                          # 输出数据（git 忽略）
```

## 隐私与安全

- 不要提交 `configs/local.yaml`，它可能包含 API Key。
- 不要提交 `user_data/` 中的个人资料。
- 不要提交 `thesis/sections/` 或 `output/` 中的生成论文。
- 如果 API Key 曾经写入公开仓库或公开聊天，请到服务商后台重置。
- AI 生成内容必须人工核查，尤其是数据、公式、引用、实验结论和学校格式要求。

## 上传 GitHub 前检查

应该留在本地：

```text
configs/local.yaml
.venv/
user_data/ 个人资料
thesis/outline.md
thesis/section_plan.json
thesis/state.json
thesis/sections/
thesis/logs/
output/
```

## 是否需要 Node.js/npm

新版 WebUI 使用 Vite + React，需要 Node.js 和 npm。

推荐版本：

- Node.js 18 或更高版本
- npm 9 或更高版本

构建后的前端文件位于 `workflows/webui/frontend/dist/`，该目录默认不提交。`python workflow.py ui` 会优先服务这个构建产物；如果还没有构建产物，会回退到旧的 Python 内置页面，方便排查环境问题。

## 许可证

MIT License
