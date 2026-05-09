#!/usr/bin/env python3
"""Rule-based quality gate for the assembled thesis Markdown.

This script is intentionally cheap and deterministic. It catches formatting and
cross-reference issues before any LLM review is considered.
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


WORK = Path(__file__).resolve().parents[2]
CONFIG_FILE = WORK / "configs" / "default.yaml"


@dataclass
class Finding:
    severity: str
    line: int
    rule: str
    message: str
    excerpt: str


def load_config():
    return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}


def configured_path(config, dotted, default):
    value = config
    for part in dotted.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return WORK / (value if isinstance(value, str) and value else default)


def line_excerpt(line, limit=120):
    line = line.strip()
    return line if len(line) <= limit else line[: limit - 3] + "..."


def check_hardcoded_refs(lines):
    findings = []
    patterns = [
        ("equation_ref", re.compile(r"(?<!\[)式\s*[（(]\s*\d+\s*[-－]\s*\d+\s*[）)]")),
        ("figure_ref", re.compile(r"(?<!\[)图\s*\d+\s*[-－]\s*\d+")),
        ("table_ref", re.compile(r"(?<!\[)表\s*\d+\s*[-－]\s*\d+")),
        ("citation_ref", re.compile(r"文献\s*\[\s*\d+\s*\]")),
    ]
    for index, line in enumerate(lines, 1):
        for rule, pattern in patterns:
            if pattern.search(line):
                findings.append(
                    Finding(
                        "warning",
                        index,
                        rule,
                        "Possible hard-coded reference. Prefer automatic cross-reference/bookmark syntax.",
                        line_excerpt(line),
                    )
                )
    return findings


def check_equation_numbering(lines):
    findings = []
    display_math = re.compile(r"^\s*\$\$(.*?)\$\$\s*$")
    number = re.compile(r"\(\s*\d+\s*[-－]\s*\d+\s*\)\s*$")
    for index, line in enumerate(lines, 1):
        match = display_math.match(line)
        if match and number.search(match.group(1)):
            findings.append(
                Finding(
                    "info",
                    index,
                    "equation_number",
                    "Display equation contains a trailing number; DOCX preprocessing will move it outside the equation object.",
                    line_excerpt(line),
                )
            )
    return findings


def check_placeholders(lines):
    findings = []
    placeholder = re.compile(r"此处插入|建议内容")
    for index, line in enumerate(lines, 1):
        if placeholder.search(line):
            findings.append(
                Finding(
                    "info",
                    index,
                    "placeholder",
                    "Figure/table placeholder or suggestion text remains in the thesis.",
                    line_excerpt(line),
                )
            )
    return findings


def check_heading_levels(lines):
    findings = []
    previous_level = 0
    for index, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if not match:
            continue
        level = len(match.group(1))
        if previous_level and level > previous_level + 1:
            findings.append(
                Finding(
                    "warning",
                    index,
                    "heading_level",
                    "Heading level jumps by more than one level.",
                    line_excerpt(line),
                )
            )
        previous_level = level
    return findings


def limit_findings(findings, max_per_rule):
    if not max_per_rule:
        return findings

    counts = {}
    limited = []
    for finding in findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
        if counts[finding.rule] <= max_per_rule:
            limited.append(finding)
    return limited


def run_checks(text, gate_config):
    lines = text.splitlines()
    findings = []
    checks = gate_config.get("checks", {})
    if checks.get("hardcoded_refs", True):
        findings.extend(check_hardcoded_refs(lines))
    if checks.get("equation_numbering", False):
        findings.extend(check_equation_numbering(lines))
    if checks.get("placeholders", True):
        findings.extend(check_placeholders(lines))
    if checks.get("heading_levels", True):
        findings.extend(check_heading_levels(lines))
    return limit_findings(findings, gate_config.get("max_findings_per_rule", 20))


def render_report(input_path, findings, gate_config):
    counts = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    lines = [
        "# Quality Gate Report",
        "",
        f"Input: `{input_path.relative_to(WORK).as_posix()}`",
        "",
        "## Summary",
        "",
        f"- findings: {len(findings)}",
        f"- warnings: {counts.get('warning', 0)}",
        f"- info: {counts.get('info', 0)}",
        f"- max findings per rule: {gate_config.get('max_findings_per_rule', 'unlimited')}",
        "",
    ]

    if findings:
        lines.extend(["## Findings", ""])
        for finding in findings:
            lines.extend(
                [
                    f"- `{finding.severity}` line {finding.line} `{finding.rule}`: {finding.message}",
                    f"  `{finding.excerpt}`",
                ]
            )
    else:
        lines.extend(["## Findings", "", "No issues found."])

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    config = load_config()
    gate_config = config.get("engines", {}).get("quality_gate", {})
    input_path = WORK / args.input if args.input else configured_path(config, "assembly.output_markdown", "output/thesis.md")
    report_path = WORK / args.report if args.report else configured_path(
        config, "engines.quality_gate.report", "output/quality_gate_report.md"
    )

    if not input_path.exists():
        raise SystemExit(f"ERROR: input not found: {input_path}")

    findings = run_checks(input_path.read_text(encoding="utf-8-sig"), gate_config)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(input_path, findings, gate_config), encoding="utf-8")

    warnings = sum(1 for finding in findings if finding.severity == "warning")
    print(f"OK: quality gate report -> {report_path} ({len(findings)} findings, {warnings} warnings)")
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
