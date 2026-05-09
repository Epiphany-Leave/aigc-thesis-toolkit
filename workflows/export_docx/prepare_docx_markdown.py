#!/usr/bin/env python3
import re
import sys
from pathlib import Path


FIGURE_PLACEHOLDER = re.compile(
    r"^👉?【此处插入图\s*([0-9]+[-－][0-9]+)\s*([^】]*)】\s*$"
)
TABLE_CAPTION = re.compile(r"^:\s*表\s*([0-9]+[-－][0-9]+)\s*(.+?)\s*$")
DISPLAY_EQUATION = re.compile(r"^\s*\$\$(.*?)\$\$\s*$")
EQUATION_NUMBER = re.compile(
    r"^(.*?)(?:\\qquad\s*)*(?:\\quad\s*)*\(\s*([0-9]+[-－][0-9]+)\s*\)\s*$"
)


def normalize_number(number):
    return number.replace("－", "-")


def eq_bookmark(number):
    return f"eq_{normalize_number(number).replace('-', '_')}"


def fig_bookmark(number):
    return f"fig_{normalize_number(number).replace('-', '_')}"


def tab_bookmark(number):
    return f"tab_{normalize_number(number).replace('-', '_')}"


def normalize_inline_refs(text):
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


def convert_display_equation(line):
    match = DISPLAY_EQUATION.match(line)
    if not match:
        return None

    body = match.group(1).strip()
    number_match = EQUATION_NUMBER.match(body)
    if not number_match:
        return line

    formula = number_match.group(1).strip()
    number = normalize_number(number_match.group(2))

    # Keep the number outside the Word equation object. Pandoc converts this
    # table to an editable equation plus a normal right-side number cell.
    return "\n".join([
        "",
        "|  |  |",
        "|:--:|--:|",
        f"| $${formula}$$ | ({number}) |",
        "",
    ])


def convert_figure_placeholder(line):
    match = FIGURE_PLACEHOLDER.match(line)
    if not match:
        return None

    number = normalize_number(match.group(1))
    title = match.group(2).strip()
    return f"\n图{number} {title}\n"


def normalize_table_caption(line):
    match = TABLE_CAPTION.match(line)
    if not match:
        return None

    number = normalize_number(match.group(1))
    title = match.group(2).strip()
    return f": 表{number} {title}"


def preprocess(text):
    text = normalize_formula_tags(text)
    lines = []

    for line in text.splitlines():
        equation = convert_display_equation(line)
        if equation is not None:
            lines.append(equation)
            continue

        figure = convert_figure_placeholder(line)
        if figure is not None:
            lines.append(figure)
            continue

        table_caption = normalize_table_caption(line)
        if table_caption is not None:
            lines.append(table_caption)
            continue

        lines.append(normalize_inline_refs(line))

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
