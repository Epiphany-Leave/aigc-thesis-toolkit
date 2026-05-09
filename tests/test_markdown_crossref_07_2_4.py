#!/usr/bin/env python3
import re
import subprocess
import zipfile
from pathlib import Path


WORK = Path("/mnt/c/Users/Epiphanye/OneDrive/Desktop/bishe/wsl")
SRC = WORK / "thesis/sections/07_experiment_7.2.4.md"
OUT_DIR = WORK / "thesis/output/crossref_test"
MD_OUT = OUT_DIR / "07_experiment_7.2.4_crossref_test.md"
DOCX_OUT = OUT_DIR / "07_experiment_7.2.4_crossref_test.docx"
REF = WORK / "template/reference.docx"

EQ_IDS = {
    "7-25": "eq:ch7_qpr_tustin",
    "7-26": "eq:ch7_qpr_discrete",
    "7-27": "eq:ch7_qpr_coefficients",
    "7-28": "eq:ch7_qpr_difference",
    "7-29": "eq:ch7_qpr_total_output",
}


def pandoc_path():
    try:
        import pypandoc

        candidate = Path(pypandoc.__file__).parent / "files" / "pandoc"
        if candidate.exists():
            return str(candidate)
    except Exception:
        pass
    return "pandoc"


def convert_refs(line):
    def repl(match):
        number = match.group(1)
        eq_id = EQ_IDS.get(number)
        if not eq_id:
            return match.group(0)
        return f"[式({number})](#{eq_id})"

    return re.sub(r"式\(([0-9]+-[0-9]+)\)", repl, line)


def convert_equation(line):
    match = re.match(r"^\s*\$\$(.*?)\s+(?:\\qquad\s*)*(?:\\quad\s*)*\(([0-9]+-[0-9]+)\)\$\$\s*$", line)
    if not match:
        return None

    formula, number = match.groups()
    eq_id = EQ_IDS.get(number)
    if not eq_id:
        return line

    return "\n".join([
        "",
        f'<span id="{eq_id}"></span>',
        "",
        "|  |  |",
        "|:--:|--:|",
        f"| $${formula.strip()}$$ | ({number}) |",
        "",
    ])


def build_markdown():
    lines = []
    for line in SRC.read_text(encoding="utf-8-sig").splitlines():
        equation = convert_equation(line)
        if equation is not None:
            lines.append(equation)
        else:
            lines.append(convert_refs(line))
    return "\n".join(lines) + "\n"


def inspect_docx():
    with zipfile.ZipFile(DOCX_OUT) as docx:
        xml = docx.read("word/document.xml").decode("utf-8", errors="ignore")

    return {
        "hyperlink_count": xml.count("<w:hyperlink"),
        "anchor_links": len(re.findall(r'<w:hyperlink[^>]+w:anchor="[^"]+"', xml)),
        "bookmark_count": xml.count("<w:bookmarkStart"),
        "has_eq_bookmark": "eq:ch7_qpr_tustin" in xml or "eq_ch7_qpr_tustin" in xml,
        "has_ref_text": "式(7-25)" in xml,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text(build_markdown(), encoding="utf-8")

    cmd = [
        pandoc_path(),
        str(MD_OUT),
        "-f",
        "markdown+link_attributes+bracketed_spans",
        "-t",
        "docx",
        f"--reference-doc={REF}",
        "-o",
        str(DOCX_OUT),
    ]
    subprocess.run(cmd, check=True)

    print(f"OK: markdown {MD_OUT}")
    print(f"OK: docx {DOCX_OUT}")
    for key, value in inspect_docx().items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
