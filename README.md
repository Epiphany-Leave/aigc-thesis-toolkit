# AIGC Thesis Toolkit

这个工程的目标是：让使用者把自己的资料放进 `user_data/`，配置一个 OpenAI 兼容 API，然后自动得到论文 Markdown 和 Word 文档。

正常情况下，`thesis/` 只需要保留这些固定内容：

```text
thesis/
  style.md
  logs/
  sections/
```

其中 `logs/` 和 `sections/` 可以是空文件夹。`thesis/outline.md`、`thesis/section_plan.json`、`thesis/state.json` 都是运行流程时自动生成的个人中间文件，不需要手工维护，也不应该当作公共参考内容。

## 总流程

```text
user_data/ 个人资料
        -> AI 自动生成 user_data/resources.md
        -> 自动生成 thesis/outline.md
        -> 自动生成 thesis/section_plan.json
        -> OpenAI 兼容 API 逐小节生成 thesis/sections/
        -> 合并为 output/thesis.md
        -> 导出 output/thesis.docx
```

统一入口是：

```bash
python workflow.py ...
```

## 固定目录

```text
configs/
  default.yaml              工程配置

template/
  reference.docx            Word 样式模板

thesis/
  style.md                  写作与格式规范
  sections/                 自动生成的分章节 Markdown
  logs/                     日志目录

user_data/
  resources.md              AI 自动生成的个人资料索引
  参考图片、参考文献、程序、仿真、绘图、实物、报告等

output/
  thesis.md                 合并后的完整 Markdown
  thesis.docx               最终 Word 文档
```

`user_data/`、`thesis/sections/`、`thesis/logs/`、`output/` 里的内容因人而异，默认不提交到版本库。

## 第一次使用

### 1. 安装依赖

建议在 WSL 中使用项目虚拟环境，避免 Ubuntu 的系统 Python 触发 `externally-managed-environment`：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

之后只要当前终端前面显示 `(.venv)`，就可以继续运行 `python workflow.py ...`。新开终端后先执行：

```bash
source .venv/bin/activate
```

如果系统已经安装 Pandoc，可以继续使用系统 Pandoc；否则依赖中的 `pypandoc-binary` 会提供 Pandoc。

### 2. 初始化固定结构

```bash
python workflow.py init
```

这个命令只会补齐固定目录和 `thesis/style.md`。  
它不会创建 `thesis/outline.md`，因为大纲应该由 AI 根据 `user_data/` 提取生成。

### 3. 准备个人资料

把自己的资料放入 `user_data/`，例如：

```text
user_data/
  参考文献/
  参考图片/
  程序/
  仿真/
  绘图/
  实物/
  开题报告.pdf
  中期报告.pdf
  范例论文.docx
```

`user_data/resources.md` 不需要手写。运行 `python workflow.py resources --overwrite` 或 `python workflow.py outline` 时，系统会先扫描 `user_data/`，再调用 AI 自动生成资料索引。

### 4. 配置写作规范

编辑：

```text
thesis/style.md
configs/default.yaml
```

`thesis/style.md` 写论文格式、章节表达、公式、图题、表题、引用等规范。  
`configs/default.yaml` 至少修改论文题目：

```yaml
project:
  title: "你的论文题目"
```

如果没有现成的 `thesis/style.md`，运行 `python workflow.py outline` 时会先尝试根据 `user_data/` 中的学校模板、任务书、开题报告、论文范例等线索自动生成。也可以单独运行：

```bash
python workflow.py style --overwrite
```

## 配置 OpenAI 兼容 API

本工程只要求接口兼容 OpenAI Chat Completions，不绑定某一家服务。

优先直接编辑：

```text
configs/default.yaml
```

```yaml
engines:
  generation:
    providers:
      writer:
        api_base: "https://api.openai.com/v1"
        api_key: "你的 API Key"
        model: "gpt-4o-mini"
```

如果使用其他兼容平台，替换 `api_base` 和 `model` 即可。`api_key` 留空时，仍会回退读取 `OPENAI_API_KEY` 等环境变量。

连续生成压力也在 YAML 中控制：

```yaml
engines:
  generation:
    batch:
      max_sections_per_run: 0
      sleep_seconds: 3
      request_timeout_seconds: 180
```

默认 `generate --all` 会连续串行生成所有未完成小节。它不会并发请求；上一小节 API 返回并写入文件后，才会等待 `sleep_seconds`，再开始下一小节。

## 生成论文

### 1. 生成大纲

```bash
python workflow.py outline
```

这个命令会扫描 `user_data/`，读取可解析的文本资料，并把 PDF、Word、图片等二进制文件作为文件名线索提供给模型，然后生成：

```text
thesis/outline.md
```

如果已经有大纲并且想重写：

```bash
python workflow.py outline --overwrite
```

### 2. 生成章节计划

```bash
python workflow.py plan
```

这个命令会根据 `thesis/outline.md` 的二级标题识别章、三级标题识别小节，并自动生成：

```text
thesis/section_plan.json
thesis/state.json
```

小节生成与合并顺序由 `outline.md` 决定，不需要用户自己维护列表。

查看状态：

```bash
python workflow.py status
```

### 3. 生成小节正文

生成下一个小节：

```bash
python workflow.py generate
```

生成全部未完成小节：

```bash
python workflow.py generate --all
```

默认会连续串行生成所有未完成小节。如果想临时限制本次只生成几个小节：

```bash
python workflow.py generate --all --max-sections 3
```

暂停生成：

```bash
python workflow.py pause
```

暂停不会硬中断正在请求的小节；当前小节完成后，会停在下一个小节开始前。继续生成：

```bash
python workflow.py resume
python workflow.py generate --all
```

只生成某一章：

```bash
python workflow.py generate --only 章节id
```

已有章节默认不会覆盖。如需重写：

```bash
python workflow.py generate --only 章节id --overwrite
```

### 4. 合并并导出 Word

```bash
python workflow.py build
```

输出文件：

```text
output/thesis.md
output/thesis.docx
output/quality_gate_report.md
```

如果只想把已有 `output/thesis.md` 重新导出为 Word：

```bash
python workflow.py build --no-assemble
```

## 一次性运行

确认 `user_data/` 已准备好，并且 API 已经在 `configs/default.yaml` 中配置后，可以运行：

```bash
python workflow.py all
```

它会依次执行：

```text
初始化固定目录
生成大纲
生成章节计划
按安全批量生成章节
全部章节完成后合并并导出 Word
```

默认 `python workflow.py all` 会自动连续推进所有未完成小节，但始终是串行生成。需要暂停时运行 `python workflow.py pause`，当前小节完成后会停下。

## WebUI

可以启动本地 WebUI，避免反复输入命令：

```bash
python workflow.py ui
```

然后打开：

```text
http://127.0.0.1:8765
```

页面中可以完成初始化之后的主要操作：填写论文题目和 API，编辑或导入写作规范，自动生成写作规范，上传 `user_data/` 资料，查看小节进度，启动完整流程，继续生成正文，暂停，恢复，刷新资料索引，重建大纲，重建小节计划和构建 Word。WebUI 保存的题目和 API 会写入 `configs/local.yaml`，这个文件默认不会提交到 GitHub。

页面还会实时预览已经生成的小节内容，不需要等 Word 导出后才检查正文。

关闭 WebUI：

```text
点击页面里的“关闭 WebUI”
```

如果 WebUI 是在当前终端前台运行，也可以按 `Ctrl+C`。如果之前开过后台旧服务，使用：

```bash
pkill -f workflows/webui/server.py
```

再重新启动：

```bash
python workflow.py ui
```

## Word 导出能力

导出流程会使用 `template/reference.docx` 作为样式模板，并处理：

- 公式编号与公式样式
- 公式交叉引用
- 图题、表题与交叉引用
- 表格样式和表格内容样式
- 目录样式
- 摘要、目录、正文页码
- 大章节分页

打开 `output/thesis.docx` 后，如果 Word 提示更新域，请选择更新，以刷新目录页码和交叉引用显示。

## 质量检查

构建时会生成：

```text
output/quality_gate_report.md
```

这是规则检查，不调用 AI，不消耗 token。它用于发现硬编码引用、占位符、标题层级等问题。

## 最短上手命令

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python workflow.py init
python workflow.py ui
```

然后打开 WebUI：

```text
http://127.0.0.1:8765
```

后续在页面里完成：填写 API 和论文题目、编辑写作规范、上传资料、点击“开始完整流程”。不需要再反复回到命令行运行 `outline`、`plan`、`generate --all` 和 `build`。

最终结果在：

```text
output/thesis.docx
```

## 上传 GitHub 前检查

建议提交这些通用文件：

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

不要提交个人文件和生成物：

```text
configs/local.yaml
.venv/
user_data/ 中的个人资料
thesis/outline.md
thesis/section_plan.json
thesis/state.json
thesis/sections/
thesis/logs/
output/
```

如果 API Key 曾经写进 `configs/default.yaml` 或发到公开位置，请在服务商后台重置一次旧 Key。
