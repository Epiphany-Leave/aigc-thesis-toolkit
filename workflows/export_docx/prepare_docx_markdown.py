#!/usr/bin/env python3
import re
import sys
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"

FIGURE_PLACEHOLDER = re.compile(
    r"^👉?【此处插入图\s*([0-9]+[-－][0-9]+)\s*([^】]*)】\s*$"
)
MARKDOWN_IMAGE = re.compile(r"^!\[(.*?)\]\((.*?)\)\s*$")
HTML_IMAGE = re.compile(r"^<img\b[^>]*>\s*$", re.IGNORECASE)
TABLE_CAPTION = re.compile(r"^:\s*表\s*([0-9]+[-－][0-9]+)\s*(.+?)\s*$")
DISPLAY_EQUATION = re.compile(r"^\s*\$\$(.*?)\$\$\s*$")
EQUATION_NUMBER = re.compile(
    r"^(.*?)(?:\\qquad\s*)*(?:\\quad\s*)*\(\s*([0-9]+[-－][0-9]+)\s*\)\s*$"
)
STANDALONE_EQUATION_NUMBER = re.compile(r"^\s*\(\s*([0-9]+[-－][0-9]+)\s*\)\s*$")
ORDERED_LIST_ITEM = re.compile(r"^(\s*)\d+[.、]\s+(.+?)\s*$")


def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    result = dict(base)
    for key, value in override.items():
        result[key] = deep_merge(result.get(key), value) if key in result else value
    return result


def load_config():
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    config = config or {}
    if LOCAL_CONFIG_FILE.exists():
        local = yaml.safe_load(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) or {}
        config = deep_merge(config, local)
    return config


def normalize_number(number):
    return number.replace("－", "-")


def eq_bookmark(number):
    return f"eq_{normalize_number(number).replace('-', '_')}"


def fig_bookmark(number):
    return f"fig_{normalize_number(number).replace('-', '_')}"


def tab_bookmark(number):
    return f"tab_{normalize_number(number).replace('-', '_')}"


def normalize_inline_refs(text, enable_links=False):
    if not enable_links:
        return text.replace("－", "-")

    text = re.sub(
        r"式\s*[（(]\s*([0-9]+[-－][0-9]+)\s*[）)]",
        lambda match: f"[式({normalize_number(match.group(1))})](#{eq_bookmark(match.group(1))})",
        text,
    )
    text = re.sub(
        r"图\s*([0-9]+[-－][0-9]+)",
        lambda match: f"[图{normalize_number(match.group(1))}](#{fig_bookmark(match.group(1))})",
        text,
    )
    text = re.sub(
        r"表\s*([0-9]+[-－][0-9]+)",
        lambda match: f"[表{normalize_number(match.group(1))}](#{tab_bookmark(match.group(1))})",
        text,
    )
    text = re.sub(
        r"文献\s*\[\s*([0-9]+)\s*\]",
        lambda match: f"文献[{match.group(1)}]",
        text,
    )
    return text


def normalize_formula_tags(text):
    text = re.sub(r"\\tag\{([^}]+)\}", r"\\qquad (\1)", text)
    text = re.sub(r"\\qquad\s*（([^）]+)）", r"\\qquad (\1)", text)
    text = re.sub(r"\\qquad\s*\(\s*([0-9]+[-－][0-9]+)\s*\)", lambda m: f"\\qquad ({normalize_number(m.group(1))})", text)
    return text


def normalize_emphasis(text):
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    return text


def normalize_ordered_list(line):
    match = ORDERED_LIST_ITEM.match(line)
    if not match:
        return line
    indent, body = match.groups()
    index = getattr(normalize_ordered_list, "index", 0) + 1
    normalize_ordered_list.index = index
    return f"{indent}（{index}）{body}"


def reset_ordered_list_counter(line):
    if not ORDERED_LIST_ITEM.match(line) and not line.startswith("   "):
        normalize_ordered_list.index = 0


def equation_table(formula, number):
    # Keep the number outside the Word equation object. Pandoc converts this
    # table to an editable equation plus a normal right-side number cell.
    return "\n".join([
        "",
        "|  |  |",
        "|:--:|--:|",
        f"| $${formula}$$ | ({number}) |",
        "",
    ])


def convert_numbered_equation(formula, number=None):
    body = formula.strip()
    if number is None:
        number_match = EQUATION_NUMBER.match(body)
        if not number_match:
            return None
        body = number_match.group(1).strip()
        number = number_match.group(2)

    body = re.sub(r"\s*\n\s*", " ", body)
    return equation_table(body, normalize_number(number))


def convert_display_equation(line, next_line=None):
    match = DISPLAY_EQUATION.match(line)
    if not match:
        return None

    body = match.group(1).strip()
    next_number = STANDALONE_EQUATION_NUMBER.match(next_line or "")
    if next_number:
        return convert_numbered_equation(body, next_number.group(1))

    converted = convert_numbered_equation(body)
    return converted if converted is not None else line


def convert_figure_placeholder(line):
    match = FIGURE_PLACEHOLDER.match(line)
    if not match:
        return None

    number = normalize_number(match.group(1))
    title = match.group(2).strip()
    return f"\n图{number} {title}\n"


def convert_image_to_placeholder(line):
    image = MARKDOWN_IMAGE.match(line)
    if image:
        title = image.group(1).strip()
    else:
        html_image = HTML_IMAGE.match(line)
        if not html_image:
            return None
        alt = re.search(r"alt=[\"']([^\"']*)[\"']", line, re.IGNORECASE)
        title = (alt.group(1) if alt else "").strip()

    match = re.search(r"图\s*([0-9]+[-－][0-9]+)\s*(.*)", title)
    if not match:
        return ""

    number = normalize_number(match.group(1))
    title_text = match.group(2).strip() or "待补充图题"
    return f"\n👉【此处插入图{number} {title_text}】\n图{number} {title_text}\n说明：此处保留插图位置，后续根据原始资料或绘图要求补充。\n"


def normalize_table_caption(line):
    match = TABLE_CAPTION.match(line)
    if not match:
        return None

    number = normalize_number(match.group(1))
    title = match.group(2).strip()
    return f": 表{number} {title}"


def preprocess(text):
    enable_links = load_config().get("export_docx", {}).get("enable_cross_reference_links", False)
    text = normalize_formula_tags(text)
    lines = []
    source_lines = text.splitlines()
    index = 0

    while index < len(source_lines):
        line = source_lines[index]
        reset_ordered_list_counter(line)

        if line.strip() == "$$":
            formula_lines = []
            end = index + 1
            while end < len(source_lines) and source_lines[end].strip() != "$$":
                formula_lines.append(source_lines[end])
                end += 1
            if end < len(source_lines):
                after = source_lines[end + 1] if end + 1 < len(source_lines) else None
                number_match = STANDALONE_EQUATION_NUMBER.match(after or "")
                if number_match:
                    lines.append(convert_numbered_equation("\n".join(formula_lines), number_match.group(1)))
                    index = end + 2
                    continue
                lines.extend(source_lines[index:end + 1])
                index = end + 1
                continue

        next_line = source_lines[index + 1] if index + 1 < len(source_lines) else None
        equation = convert_display_equation(line, next_line)
        if equation is not None:
            lines.append(equation)
            if next_line and STANDALONE_EQUATION_NUMBER.match(next_line):
                index += 2
            else:
                index += 1
            continue

        figure = convert_figure_placeholder(line)
        if figure is not None:
            lines.append(figure)
            index += 1
            continue

        image = convert_image_to_placeholder(line)
        if image is not None:
            if image:
                lines.append(image)
            index += 1
            continue

        table_caption = normalize_table_caption(line)
        if table_caption is not None:
            lines.append(table_caption)
            index += 1
            continue

        line = normalize_ordered_list(line)
        line = normalize_emphasis(line)
        lines.append(normalize_inline_refs(line, enable_links))
        index += 1

    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 3:
        print("Usage: prepare_docx_markdown.py <input.md> <output.md>", file=sys.stderr)
        return 1

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])

    text = src.read_text(encoding="utf-8-sig")
    dst.write_text(preprocess(text), encoding="utf-8")
    print(f"OK: prepared {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
