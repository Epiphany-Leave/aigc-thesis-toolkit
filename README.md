# AIGC Thesis Toolkit

AIGC Thesis Toolkit is a local thesis-writing workflow for turning your own reference materials into a structured thesis draft, Markdown manuscript, and Word document. It is designed for students who want an AI-assisted writing pipeline that is traceable, resumable, and easier to operate than a pile of one-off prompts.

The toolkit provides both a command-line workflow and a local WebUI. The recommended path is to start the WebUI, upload materials, configure your OpenAI-compatible API, and let the workflow generate the thesis section by section.

## Highlights

- **Local WebUI**: configure API settings, upload materials, edit writing rules, monitor progress, pause/resume generation, and preview generated thesis content in the browser.
- **OpenAI-compatible API support**: works with services that expose the Chat Completions API format.
- **Material-aware workflow**: scans `user_data/`, builds an AI-generated resource index, and uses your materials as writing context.
- **Automatic writing style generation**: can derive `thesis/style.md` from school templates, task books, reports, examples, and other uploaded references.
- **Small-step generation**: splits the thesis plan into subsections and generates them serially, reducing timeout and overload risk.
- **Resumable state**: tracks generated subsections in `thesis/section_plan.json` and skips completed files by default.
- **Word export**: assembles Markdown and exports `output/thesis.docx` using `template/reference.docx`.
- **Git-friendly defaults**: private inputs, generated drafts, logs, local API keys, and output files are ignored by default.

## How It Works

```text
user_data/ reference materials
        -> AI-generated user_data/resources.md
        -> AI-generated or imported thesis/style.md
        -> AI-generated thesis/outline.md
        -> thesis/section_plan.json
        -> serial subsection generation in thesis/sections/
        -> output/thesis.md
        -> output/thesis.docx
```

## Quick Start

The project is intended to run in WSL, Linux, macOS, or another Python environment with `venv` support.

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

Open the WebUI:

```text
http://127.0.0.1:8765
```

If port `8765` is already in use, the server will try the next available port and print the actual URL.

## WebUI Workflow

After opening the WebUI, you can complete the normal workflow without returning to the command line:

1. Fill in the thesis title, API Base, API Key, model, timeout, and generation interval.
2. Upload reference materials into `user_data/`.
3. Edit, import, or auto-generate `thesis/style.md`.
4. Click **Start Full Workflow** to generate the resource index, outline, subsection plan, thesis draft, and Word output.
5. Watch progress and live thesis preview as each subsection is generated.
6. Use pause/resume if you want generation to stop after the current subsection.

The WebUI saves private settings such as API keys to:

```text
configs/local.yaml
```

This file is ignored by git.

## What To Upload

Put thesis-related materials in `user_data/`, or upload them through the WebUI.

Useful examples:

- task book, proposal, mid-term report, school formatting rules
- reference papers, BibTeX files, literature notes
- simulation files, experiment logs, tables, CSV data
- circuit diagrams, flowcharts, figures, prototype photos
- previous thesis examples or school-provided Word templates

Text-like files are sampled directly. PDF, Word, image, and other binary files are currently used as file-name and path evidence unless you provide extracted text.

## API Configuration

The WebUI is the easiest place to configure API settings. For manual configuration, copy or create:

```bash
cp configs/local.example.yaml configs/local.yaml
```

Then edit `configs/local.yaml`:

```yaml
project:
  title: "Your thesis title"

engines:
  generation:
    providers:
      writer:
        api_base: "https://api.openai.com/v1"
        api_key: "your API key"
        model: "gpt-4o-mini"
    batch:
      max_sections_per_run: 0
      sleep_seconds: 3
      request_timeout_seconds: 180
```

`max_sections_per_run: 0` means `generate --all` will serially generate all pending subsections. Use a positive number if you want a single run to stop after a fixed number of subsections.

## Command Line Usage

The WebUI covers the common workflow, but every step is also available from the command line.

```bash
python workflow.py init
python workflow.py style --overwrite
python workflow.py resources --overwrite
python workflow.py outline
python workflow.py plan
python workflow.py generate --all
python workflow.py build
```

Common commands:

```bash
python workflow.py status                 # show progress
python workflow.py generate               # generate the next pending subsection
python workflow.py generate --all         # generate all pending subsections serially
python workflow.py generate --all --max-sections 3
python workflow.py pause                  # pause before the next subsection
python workflow.py resume                 # clear pause flag
python workflow.py build --no-assemble    # export existing output/thesis.md
python workflow.py ui --port 8766
```

## Outputs

Generated results are written to:

```text
output/thesis.md
output/thesis.docx
output/quality_gate_report.md
```

Intermediate generated files include:

```text
user_data/resources.md
thesis/outline.md
thesis/section_plan.json
thesis/state.json
thesis/sections/
thesis/logs/
```

These files are personal or generated and are ignored by default.

## Project Structure

```text
configs/
  default.yaml              shared default config
  local.example.yaml        example private config

template/
  reference.docx            Word style reference document

thesis/
  style.md                  writing and formatting rules
  sections/                 generated subsection Markdown files
  logs/                     workflow logs

user_data/
  README.md                 placeholder for private materials

workflows/
  write/                    outline, style, resource, section generation
  export_docx/              Markdown to Word export pipeline
  review/                   review and quality-check workflow
  webui/                    local WebUI

output/
  .gitkeep                  generated outputs are ignored
```

## Safety And Privacy

- Do not commit `configs/local.yaml`; it may contain API keys.
- Do not commit personal materials in `user_data/`.
- Do not commit generated thesis drafts in `thesis/sections/` or `output/`.
- If an API key was ever committed or shared publicly, rotate it in your provider dashboard.
- The model can make mistakes. Treat generated thesis text as a draft and verify claims, data, references, formulas, and formatting before submission.

## GitHub Publishing Checklist

Files that should normally be committed:

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

Files that should stay local:

```text
configs/local.yaml
.venv/
user_data/ personal files
thesis/outline.md
thesis/section_plan.json
thesis/state.json
thesis/sections/
thesis/logs/
output/
```

## License

See [LICENSE](LICENSE).
