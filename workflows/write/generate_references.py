#!/usr/bin/env python3
"""Generate BibTeX and a numbered references section for the thesis."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"
LOCAL_CONFIG_FILE = WORK / "configs" / "local.yaml"
sys.path.insert(0, str(WORK))

from workflows.write.generate_resources import scan_user_data_entries  # noqa: E402


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
        config = deep_merge(config, yaml.safe_load(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) or {})
    return config


def read_text(path):
    return path.read_text(encoding="utf-8-sig", errors="ignore") if path.exists() else ""


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def bib_escape(value):
    return clean_text(value).replace("{", "").replace("}", "")


def find_uploaded_bibtex(user_data_dir):
    parts = []
    if not user_data_dir.exists():
        return ""
    for path in sorted(user_data_dir.rglob("*.bib")):
        if path.name == "references.bib":
            continue
        content = read_text(path).strip()
        if content:
            parts.append(f"% Source: {path.relative_to(user_data_dir).as_posix()}\n{content}")
    return "\n\n".join(parts)


def extract_reference_lines(text):
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if re.search(r"(参考文献|references)", line, flags=re.I):
            block = []
            for candidate in lines[index + 1:index + 80]:
                stripped = candidate.strip()
                if not stripped:
                    if block:
                        block.append("")
                    continue
                if re.match(r"^#{1,6}\s+", stripped) and block:
                    break
                if re.search(r"(致谢|附录|appendix)", stripped, flags=re.I) and block:
                    break
                block.append(stripped)
            if block:
                blocks.extend(block)
    if not blocks:
        return []

    refs = []
    current = ""
    for line in blocks:
        if not line:
            continue
        starts_ref = re.match(r"^(\[\d+\]|\d+[.、]|[（(]\d+[）)])\s*", line)
        if starts_ref:
            if current:
                refs.append(current.strip())
            current = re.sub(r"^(\[\d+\]|\d+[.、]|[（(]\d+[）)])\s*", "", line).strip()
        elif current:
            current += " " + line
        elif re.search(r"\d{4}", line) and len(line) > 12:
            refs.append(line)
    if current:
        refs.append(current.strip())

    cleaned = []
    seen = set()
    for ref in refs:
        ref = clean_text(ref).strip("[] ")
        if len(ref) < 10 or ref in seen:
            continue
        seen.add(ref)
        cleaned.append(ref)
    return cleaned


def find_references_in_user_data(user_data_dir):
    refs = []
    for entry in scan_user_data_entries(user_data_dir):
        content = entry.get("content") or ""
        if not content:
            continue
        for ref in extract_reference_lines(content):
            refs.append((entry["path"], ref))
    return refs


def bib_from_reference_lines(refs):
    entries = []
    for index, (source, ref) in enumerate(refs, start=1):
        key = f"userref{index:02d}"
        year = re.search(r"(19|20)\d{2}", ref)
        fields = [
            f"  title = {{{bib_escape(ref)}}}",
            f"  note = {{{bib_escape('来源：' + source)}}}",
        ]
        if year:
            fields.append(f"  year = {{{year.group(0)}}}")
        entries.append(f"@misc{{{key},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries)


def parse_bib_entries(bibtex):
    entries = []
    for match in re.finditer(r"@(\w+)\s*\{\s*([^,]+)\s*,(.*?)(?=\n@\w+\s*\{|\Z)", bibtex, flags=re.S):
        entry_type, key, body = match.groups()
        fields = {}
        for field, braced, quoted in re.findall(r"(\w+)\s*=\s*(?:\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|\"([^\"]*)\")", body):
            fields[field.lower()] = clean_text(braced or quoted)
        if not fields:
            for field, value in re.findall(r"(\w+)\s*=\s*\{(.*?)\}\s*,?", body, flags=re.S):
                fields[field.lower()] = clean_text(value)
        entries.append({"type": entry_type, "key": key.strip(), "fields": fields})
    return entries


def author_text(authors):
    if isinstance(authors, str):
        authors = [item.strip() for item in re.split(r"\s+and\s+", authors) if item.strip()]
    names = []
    for author in authors or []:
        if isinstance(author, dict):
            family = clean_text(author.get("family"))
            given = clean_text(author.get("given"))
            names.append(clean_text(f"{family} {given}"))
        else:
            names.append(clean_text(author))
    if not names:
        return "作者不详"
    return ", ".join(names[:3]) + (" 等" if len(names) > 3 else "")


def format_reference_from_fields(fields):
    note = clean_text(fields.get("note"))
    authors = author_text(fields.get("author", ""))
    title = clean_text(fields.get("title"))
    journal = clean_text(fields.get("journal") or fields.get("journaltitle") or fields.get("booktitle"))
    year = clean_text(fields.get("year"))
    volume = clean_text(fields.get("volume"))
    number = clean_text(fields.get("number"))
    pages = clean_text(fields.get("pages"))
    doi = clean_text(fields.get("doi"))
    tail = []
    if journal:
        tail.append(journal)
    if year:
        tail.append(year)
    if volume:
        tail.append(volume + (f"({number})" if number else ""))
    if pages:
        tail.append(pages)
    result = f"{authors}. {title}."
    if tail:
        result += " " + ", ".join(tail) + "."
    if doi:
        result += f" DOI: {doi}."
    if note.startswith("来源："):
        result += f" {note}."
    return result


def crossref_items(query, rows, timeout):
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
        {"query": query, "rows": rows, "select": "DOI,title,author,published-print,published-online,container-title,volume,issue,page,type"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "aigc-thesis-toolkit/0.1 (mailto:unknown@example.com)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("message", {}).get("items", [])


def item_year(item):
    for key in ("published-print", "published-online"):
        parts = item.get(key, {}).get("date-parts") or []
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def bib_from_crossref_item(item, index):
    title = clean_text((item.get("title") or [""])[0])
    journal = clean_text((item.get("container-title") or [""])[0])
    year = item_year(item)
    doi = clean_text(item.get("DOI"))
    key_seed = re.sub(r"[^A-Za-z0-9]+", "", (doi or title or f"ref{index}"))[:24] or f"ref{index}"
    authors = item.get("author") or []
    author_field = " and ".join(clean_text(f"{a.get('family', '')}, {a.get('given', '')}") for a in authors if a.get("family"))
    entry_type = "article" if item.get("type") == "journal-article" else "misc"
    fields = [
        f"  title = {{{bib_escape(title)}}}",
    ]
    if author_field:
        fields.append(f"  author = {{{bib_escape(author_field)}}}")
    if journal:
        fields.append(f"  journal = {{{bib_escape(journal)}}}")
    if year:
        fields.append(f"  year = {{{year}}}")
    if item.get("volume"):
        fields.append(f"  volume = {{{bib_escape(item.get('volume'))}}}")
    if item.get("issue"):
        fields.append(f"  number = {{{bib_escape(item.get('issue'))}}}")
    if item.get("page"):
        fields.append(f"  pages = {{{bib_escape(item.get('page'))}}}")
    if doi:
        fields.append(f"  doi = {{{bib_escape(doi)}}}")
    return f"@{entry_type}{{{key_seed},\n" + ",\n".join(fields) + "\n}"


def query_terms(config):
    user_data_dir = WORK / config.get("paths", {}).get("user_data_dir", "user_data")
    title = config.get("project", {}).get("title", "")
    resources = read_text(user_data_dir / "resources.md")
    terms = [title]
    keywords = [
        "STM32 autonomous vehicle temperature control medicine delivery",
        "contactless temperature measurement STM32 robot",
        "line tracking medicine delivery robot",
    ]
    if "STM32" in title or "单片机" in title or "STM32" in resources:
        terms.extend(keywords)
    return [term for term in terms if term.strip()]


def dedupe_items(items):
    seen = set()
    result = []
    for item in items:
        doi = clean_text(item.get("DOI")).lower()
        title = clean_text((item.get("title") or [""])[0]).lower()
        key = doi or title
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def build_references_markdown(entries):
    lines = ["# 参考文献", ""]
    for index, entry in enumerate(entries, start=1):
        lines.append(f"[{index}] {format_reference_from_fields(entry['fields'])}")
    if len(lines) == 2:
        lines.append("[1] TODO：请补充与课题直接相关的真实参考文献。")
    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true", help="overwrite generated references")
    parser.add_argument("--rows", type=int, default=12, help="maximum Crossref items")
    parser.add_argument("--timeout", type=int, default=30, help="Crossref request timeout")
    args = parser.parse_args()

    config = load_config()
    user_data_dir = WORK / config.get("paths", {}).get("user_data_dir", "user_data")
    thesis_dir = WORK / config.get("paths", {}).get("thesis_dir", "thesis")
    references_md = WORK / config.get("references", {}).get("output_markdown", "thesis/references.md")
    references_bib = WORK / config.get("references", {}).get("output_bibtex", "user_data/references.bib")

    if references_md.exists() and references_bib.exists() and not args.overwrite:
        print(f"SKIP: references exist: {references_md}")
        return 0

    user_data_dir.mkdir(parents=True, exist_ok=True)
    thesis_dir.mkdir(parents=True, exist_ok=True)
    bibtex = find_uploaded_bibtex(user_data_dir)
    if not bibtex.strip():
        refs = find_references_in_user_data(user_data_dir)
        if refs:
            bibtex = bib_from_reference_lines(refs)

    if not bibtex.strip():
        items = []
        for term in query_terms(config):
            try:
                items.extend(crossref_items(term, args.rows, args.timeout))
            except Exception as exc:  # noqa: BLE001 - best effort reference retrieval.
                print(f"WARN: Crossref query failed for {term!r}: {exc}")
        bibtex = "\n\n".join(bib_from_crossref_item(item, idx) for idx, item in enumerate(dedupe_items(items)[:args.rows], 1))

    if not bibtex.strip():
        bibtex = "@misc{todo_references,\n  title = {TODO: 补充与课题直接相关的真实参考文献},\n  year = {2026}\n}\n"

    references_bib.write_text(bibtex.strip() + "\n", encoding="utf-8")
    entries = parse_bib_entries(bibtex)
    references_md.write_text(build_references_markdown(entries), encoding="utf-8")
    print(f"OK: references bib -> {references_bib}")
    print(f"OK: references markdown -> {references_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
