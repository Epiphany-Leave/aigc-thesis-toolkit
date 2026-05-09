# AIGC Thesis Toolkit

![AIGC Thesis Toolkit WebUI](image.png)

AIGC Thesis Toolkit 是一个本地运行的 AI 论文写作工作流。它可以把你放入 `user_data/` 的参考资料、学校格式要求、开题/中期报告、参考论文、仿真或实验数据等内容，整理成可追踪的资料索引，并辅助生成论文大纲、小节正文、完整 Markdown 和 Word 文档。

这个项目的目标不是“一键交作业”，而是提供一个更稳定、更可控、更容易续写的 AIGC 论文工作台：你提供真实资料和格式要求，系统按小节串行生成内容，并保留中间文件、状态和预览，方便你检查、修改和导出。

## 功能亮点

- **本地 WebUI 工作台**：在浏览器里配置 API、上传资料、编辑/导入写作规范、启动生成、暂停/继续、查看进度和实时预览正文。
- **支持 OpenAI 兼容接口**：只要服务兼容 Chat Completions 格式，就可以通过 `api_base`、`api_key`、`model` 接入。
- **自动资料索引**：扫描 `user_data/`，生成 `user_data/resources.md`，让模型知道有哪些可用资料。
- **自动写作规范**：可以从学校模板、任务书、开题报告、论文范例等资料中生成 `thesis/style.md`，也可以手动导入。
- **按小节串行生成**：把论文大纲拆成小节任务，上一小节完成后再进入下一小节，降低长文本超时和 API 卡死概率。
- **可暂停、可续写**：生成进度记录在 `thesis/section_plan.json`，已经完成的小节默认不会重复生成。
- **导出 Word**：把生成的小节合并成 `output/thesis.md`，再按 `template/reference.docx` 导出 `output/thesis.docx`。
- **适合上传 GitHub**：API Key、个人资料、生成正文、日志和输出文件默认不会提交。

## 工作流程

```text
user_data/ 个人资料
        -> AI 生成 user_data/resources.md
        -> AI 生成或导入 thesis/style.md
        -> AI 生成 thesis/outline.md
        -> 生成 thesis/section_plan.json
        -> 逐小节生成 thesis/sections/
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
python workflow.py ui
```

打开浏览器：

```text
http://127.0.0.1:8765
```

如果 `8765` 端口已被占用，程序会自动尝试后续端口，并在终端输出实际地址。

## WebUI 使用方式

启动 WebUI 后，常规流程都可以在页面里完成：

1. 填写论文题目、API Base、API Key、模型、超时时间和小节间隔。
2. 上传论文相关资料到 `user_data/`。
3. 编辑、导入或自动生成 `thesis/style.md` 写作规范。
4. 点击“开始完整流程”。
5. 在页面右侧查看任务输出和实时论文预览。
6. 需要停下时点击“暂停”，当前小节完成后会停在下一小节之前。
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
    providers:
      writer:
        api_base: "https://api.openai.com/v1"
        api_key: "你的 API Key"
        model: "gpt-4o-mini"
    batch:
      max_sections_per_run: 0
      sleep_seconds: 3
      request_timeout_seconds: 180
```

说明：

- `max_sections_per_run: 0` 表示 `generate --all` 会连续串行生成所有未完成小节。
- 如果想限制单次最多生成 3 个小节，可以设为 `3`。
- `sleep_seconds` 是两个小节请求之间的等待时间。
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
python workflow.py generate               # 生成下一个未完成小节
python workflow.py generate --all         # 串行生成全部未完成小节
python workflow.py generate --all --max-sections 3
python workflow.py pause                  # 当前小节完成后暂停
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
configs/
  default.yaml              公共默认配置
  local.example.yaml        私有配置示例

template/
  reference.docx            Word 样式模板

thesis/
  style.md                  写作与格式规范
  sections/                 生成的小节 Markdown
  logs/                     运行日志

user_data/
  README.md                 个人资料目录占位说明

workflows/
  write/                    资料、规范、大纲、小节生成
  export_docx/              Markdown 到 Word 的导出流程
  review/                   质量检查与审阅流程
  webui/                    本地 WebUI

output/
  .gitkeep                  输出目录占位，生成物默认忽略
```

## 隐私与安全

- 不要提交 `configs/local.yaml`，它可能包含 API Key。
- 不要提交 `user_data/` 中的个人资料。
- 不要提交 `thesis/sections/` 或 `output/` 中的生成论文。
- 如果 API Key 曾经写入公开仓库或公开聊天，请到服务商后台重置。
- AI 生成内容必须人工核查，尤其是数据、公式、引用、实验结论和学校格式要求。

## 上传 GitHub 前检查

通常应该提交：

```text
README.md
requirements.txt
workflow.py
configs/default.yaml
configs/local.example.yaml
workflows/
template/
thesis/README.md
thesis/style.md
user_data/README.md
.gitignore
```

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

当前 WebUI 使用 Python 标准库实现，不需要 Node.js 和 npm。这样安装更轻量，适合直接在 WSL 或 Linux 上运行。

如果后续要做更复杂的交互，比如拖拽式文件管理、富文本预览、可视化章节编辑器、多页面路由等，可以再引入 Vite/React 或其他前端工具链。届时 README 会补充 Node.js/npm 的安装和构建步骤。

## License

见 [LICENSE](LICENSE)。
