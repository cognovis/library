#!/usr/bin/env python3
"""Audit skill and agent prose for MCP migration debt.

The audit scans installed skill/agent markdown files for CLI command recipes that
should migrate to typed `cognovis-tools` MCP verbs or `library.exec`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CLASS_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
DEFAULT_PATHS = [
    Path.home() / ".agents" / "skills" / "beads" / "SKILL.md",
    Path.home() / ".agents" / "skills" / "session-close" / "SKILL.md",
    Path.home() / ".agents" / "skills" / "bead-reviewer" / "SKILL.md",
    Path.home() / ".claude" / "agents" / "bead-orchestrator.md",
    Path.home() / ".claude" / "agents" / "quick-fix.md",
    Path.home() / ".claude" / "agents" / "session-close.md",
]


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    default_classification: str
    typed_tool: str
    notes: str


@dataclass(frozen=True)
class Finding:
    line: int
    command: str
    classification: str
    typed_tool: str
    snippet: str
    rationale: str


@dataclass(frozen=True)
class FileAudit:
    path: Path
    findings: tuple[Finding, ...]
    summary_classification: str
    a_b_hits: int
    notes: str

    @property
    def hit_count(self) -> int:
        return len(self.findings)


RULES = [
    Rule(
        name="bd create",
        pattern=re.compile(r"\bbd create\b"),
        default_classification="A",
        typed_tool="mcp__cognovis-tools__bead.create",
        notes="Explicit bead creation recipe should route to the typed bead.create tool.",
    ),
    Rule(
        name="bd update",
        pattern=re.compile(r"\bbd update\b"),
        default_classification="A",
        typed_tool="mcp__cognovis-tools__bead.update",
        notes="Explicit bead mutation recipe should route to the typed bead.update tool.",
    ),
    Rule(
        name="bd close",
        pattern=re.compile(r"\bbd close\b"),
        default_classification="A",
        typed_tool="mcp__cognovis-tools__bead.close",
        notes="Explicit bead close recipe should route to the typed bead.close tool.",
    ),
    Rule(
        name="bd show",
        pattern=re.compile(r"\bbd show\b"),
        default_classification="A",
        typed_tool="mcp__cognovis-tools__bead.show",
        notes="Explicit bead read recipe should route to the typed bead.show tool.",
    ),
    Rule(
        name="bd list",
        pattern=re.compile(r"\bbd list\b"),
        default_classification="A",
        typed_tool="mcp__cognovis-tools__bead.list",
        notes="Explicit bead list recipe should route to the typed bead.list tool.",
    ),
    Rule(
        name="bd search",
        pattern=re.compile(r"\bbd search\b"),
        default_classification="A",
        typed_tool="mcp__cognovis-tools__bead.search",
        notes="Explicit bead search recipe should route to the typed bead.search tool.",
    ),
    Rule(
        name="git add",
        pattern=re.compile(r"\bgit add\b"),
        default_classification="B",
        typed_tool="mcp__cognovis-tools__git.stage_paths or mcp__cognovis-tools__library.exec",
        notes="Git staging instructions are a migration candidate for typed git tools or library.exec.",
    ),
    Rule(
        name="git commit",
        pattern=re.compile(r"\bgit commit\b"),
        default_classification="B",
        typed_tool="mcp__cognovis-tools__git.commit or mcp__cognovis-tools__library.exec",
        notes="Git commit recipes are a migration candidate for typed git tools or library.exec.",
    ),
    Rule(
        name="git merge",
        pattern=re.compile(r"\bgit merge\b"),
        default_classification="B",
        typed_tool="mcp__cognovis-tools__git.merge_from_main or mcp__cognovis-tools__library.exec",
        notes="Git merge recipes are a migration candidate for typed git tools or library.exec.",
    ),
    Rule(
        name="git pull",
        pattern=re.compile(r"\bgit pull\b"),
        default_classification="B",
        typed_tool="mcp__cognovis-tools__git.pull or mcp__cognovis-tools__library.exec",
        notes="Git pull recipes are a migration candidate for typed git tools or library.exec.",
    ),
    Rule(
        name="git push",
        pattern=re.compile(r"\bgit push\b"),
        default_classification="B",
        typed_tool="mcp__cognovis-tools__git.push or mcp__cognovis-tools__library.exec",
        notes="Git push recipes are a migration candidate for typed git tools or library.exec.",
    ),
    Rule(
        name="git status",
        pattern=re.compile(r"\bgit status\b"),
        default_classification="B",
        typed_tool="mcp__cognovis-tools__git.status or mcp__cognovis-tools__library.exec",
        notes="Git status probes are a migration candidate for typed git tools or library.exec.",
    ),
    Rule(
        name="bd dolt",
        pattern=re.compile(r"\bbd dolt\b"),
        default_classification="B",
        typed_tool="mcp__cognovis-tools__library.exec",
        notes="Dolt workflow recipes are a migration candidate for library.exec until a typed surface exists.",
    ),
]


NEGATION_MARKERS = (
    "do not ",
    "do not use",
    "never use",
    "do n't",
    "don't use",
    "avoid ",
    "for debugging",
    "debug only",
    "manual fallback",
    "manual recovery",
    "if the runner is unavailable",
    "unavailable or returns",
    "not applicable",
)
CONTEXTUAL_MARKERS = (
    "for example",
    "example",
    "examples",
    "e.g.",
    "such as",
    "probe",
    "load bead data",
    "extract",
    "check ",
    "verify ",
    "status",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional paths to scan. Defaults to the installed skill/agent audit scope.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a markdown report to this path.",
    )
    parser.add_argument(
        "--check-class",
        choices=("A", "B", "C", "D"),
        help="Exit non-zero when any finding at or above this classification is present.",
    )
    parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit machine-readable JSON to stdout.",
    )
    return parser.parse_args()


def _is_markdown_table_pipe(stripped: str) -> bool:
    # Markdown table rows typically have 2+ `|` separators surrounded by
    # whitespace (e.g. "| col1 | col2 |"). A shell pipe is preceded by a
    # command token and does not appear repeatedly between space-padded cells.
    table_separator_count = len(re.findall(r"\s\|\s", stripped))
    starts_with_pipe = stripped.startswith("|")
    return table_separator_count >= 2 or (starts_with_pipe and table_separator_count >= 1)


def is_explicit_recipe(line: str, in_code_block: bool) -> bool:
    stripped = line.strip()
    if in_code_block:
        return True
    # Strip leading Markdown blockquote markers (one or more `>` with optional
    # spacing) before inspecting the line for shell-recipe indicators. A line
    # like "> Do not run `bd close`" is prose inside a quote, not a shell
    # redirection.
    recipe_body = re.sub(r"^(?:\s*>\s*)+", "", stripped)
    if recipe_body.startswith(("`bd ", "`git ", "bd ", "git ")):
        return True
    # Shell-style markers that are unambiguous when present.
    if any(token in recipe_body for token in ("--", "&&", "<", "$(")):
        return True
    # `|` only counts as a shell pipe when it is not part of a Markdown table.
    if "|" in recipe_body and not _is_markdown_table_pipe(recipe_body):
        return True
    # `>` only counts as a shell redirection after blockquote markers have been
    # stripped — i.e. the redirection sign must appear inside the actual
    # command body.
    if ">" in recipe_body:
        return True
    if re.match(r"^[0-9]+\.\s", recipe_body):
        return True
    return False


def _negation_is_primary_intent(rule: Rule, line: str) -> bool:
    """Return True when the line's primary intent is to prohibit the command.

    A negation marker downgrades a finding to D only when:
      * the negation marker appears in the line, AND
      * the negation marker appears before the matched command, AND
      * the line is not an explicit invocation recipe that explains *how*
        the command would be used (e.g. "Avoid `bd create --title=...`
        because ...").

    When the negation appears after the command, or alongside a full
    invocation recipe, the line is still teaching the invocation and must
    retain its original classification.
    """
    lowered = line.lower()
    negation_positions = [
        lowered.find(marker) for marker in NEGATION_MARKERS if marker in lowered
    ]
    if not negation_positions:
        return False
    first_negation = min(negation_positions)
    command_match = rule.pattern.search(line)
    if command_match is None:
        # No command on the line — treat negation as primary intent so the
        # finding falls through to D, matching the previous behaviour.
        return True
    command_position = command_match.start()
    if first_negation > command_position:
        # Negation appears after the command (e.g. "`bd close` should never
        # be run by hand") — still a recipe-ish mention of the command, so
        # do not downgrade.
        return False
    # Negation appears before the command. Only treat as primary intent when
    # the line is NOT an explicit recipe; otherwise the negation is part of
    # an instructional sentence that still teaches the invocation.
    return True


def classify(rule: Rule, line: str, in_code_block: bool) -> tuple[str, str]:
    lowered = line.lower()
    if "mcp__cognovis-tools__" in lowered or "library.exec" in lowered:
        return "D", "Line already references an MCP or library.exec migration target."
    explicit_recipe = is_explicit_recipe(line, in_code_block)
    has_negation = any(marker in lowered for marker in NEGATION_MARKERS)
    if has_negation and not explicit_recipe and _negation_is_primary_intent(rule, line):
        return "D", "Informational or prohibitive mention; not teaching an invocation."
    if rule.default_classification == "A":
        if explicit_recipe:
            return "A", rule.notes
        if any(marker in lowered for marker in CONTEXTUAL_MARKERS):
            return "C", "Contextual bead CLI mention; lower-priority migration."
        return "A", rule.notes
    if explicit_recipe:
        return "B", rule.notes
    if any(marker in lowered for marker in CONTEXTUAL_MARKERS):
        return "C", "Contextual git/Dolt mention; migrate during broader refactors."
    return "B", rule.notes


def audit_path(path: Path) -> FileAudit:
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    in_code_block = False
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        for rule in RULES:
            if not rule.pattern.search(raw_line):
                continue
            classification, rationale = classify(rule, raw_line, in_code_block)
            findings.append(
                Finding(
                    line=line_no,
                    command=rule.name,
                    classification=classification,
                    typed_tool=rule.typed_tool,
                    snippet=stripped or raw_line,
                    rationale=rationale,
                )
            )

    summary_classification = "D"
    if findings:
        summary_classification = min(
            (finding.classification for finding in findings),
            key=lambda label: CLASS_RANK[label],
        )
    a_b_hits = sum(1 for finding in findings if finding.classification in {"A", "B"})
    notes = (
        "No CLI migration debt detected."
        if not findings
        else next(
            (
                finding.rationale
                for finding in findings
                if finding.classification == summary_classification
            ),
            findings[0].rationale,
        )
    )
    return FileAudit(
        path=path,
        findings=tuple(findings),
        summary_classification=summary_classification,
        a_b_hits=a_b_hits,
        notes=notes,
    )


def sort_audits(audits: Iterable[FileAudit]) -> list[FileAudit]:
    return sorted(
        audits,
        key=lambda audit: (
            -audit.a_b_hits,
            CLASS_RANK[audit.summary_classification],
            -audit.hit_count,
            str(audit.path),
        ),
    )


def file_label(path: Path) -> str:
    return str(path).replace(str(Path.home()), "~")


def build_report(audits: list[FileAudit]) -> str:
    top_five = ", ".join(file_label(audit.path) for audit in audits[:5]) or "None"
    lines = [
        "# MCP Migration Debt Audit — 2026-05-29",
        "",
        "## Scope",
        "",
        "- Audited installed skill and agent surfaces under `~/.agents/skills/` and `~/.claude/agents/`.",
        "- This worktree can report on those installed files, but their owning source files are outside the writable roots of this run.",
        "- Doctor wrapper: `scripts/check-mcp-migration-debt.sh` runs the audit in fail-on-A mode via `uv run --no-project python`.",
        f"- Top five remediation targets by A+B hit count: {top_five}",
        "",
        "## Summary",
        "",
        "| File | Hits | A+B Hits | Classification | Notes |",
        "|------|------|----------|----------------|-------|",
    ]
    for audit in audits:
        lines.append(
            f"| `{file_label(audit.path)}` | {audit.hit_count} | {audit.a_b_hits} | "
            f"{audit.summary_classification} | {audit.notes} |"
        )

    lines.extend(
        [
            "",
            "## Classification Key",
            "",
            "- A = Must Migrate (typed tool exists, anti-pattern violation)",
            "- B = Should Migrate (candidate for Phase 6 or `library.exec`)",
            "- C = Can Migrate (contextual, low priority)",
            "- D = No Migration (informational or prohibitive mention)",
            "",
            "## Detailed Findings",
            "",
        ]
    )

    for audit in audits:
        lines.extend(
            [
                f"### `{file_label(audit.path)}`",
                "",
                f"- Summary classification: **{audit.summary_classification}**",
                f"- Total hits: **{audit.hit_count}**",
                f"- A+B hits: **{audit.a_b_hits}**",
                "",
            ]
        )
        if not audit.findings:
            lines.append("- No findings.")
            lines.append("")
            continue
        for finding in audit.findings:
            lines.append(
                f"- L{finding.line} [{finding.classification}] `{finding.command}` → "
                f"`{finding.typed_tool}`. {finding.rationale} Snippet: `{finding.snippet}`"
            )
        lines.append("")
    return "\n".join(lines)


def build_json(audits: list[FileAudit]) -> str:
    payload = {
        "contract_version": "1",
        "audits": [
            {
                "path": str(audit.path),
                "hits": audit.hit_count,
                "a_b_hits": audit.a_b_hits,
                "classification": audit.summary_classification,
                "notes": audit.notes,
                "findings": [
                    {
                        "line": finding.line,
                        "command": finding.command,
                        "classification": finding.classification,
                        "typed_tool": finding.typed_tool,
                        "snippet": finding.snippet,
                        "rationale": finding.rationale,
                    }
                    for finding in audit.findings
                ],
            }
            for audit in audits
        ],
    }
    return json.dumps(payload, indent=2)


def resolve_paths(raw_paths: list[str]) -> list[Path]:
    if raw_paths:
        return [Path(path).expanduser() for path in raw_paths]
    return DEFAULT_PATHS[:]


def check_missing(paths: Iterable[Path]) -> list[str]:
    missing: list[str] = []
    for path in paths:
        if not path.exists():
            missing.append(str(path))
    return missing


def main() -> int:
    args = parse_args()
    paths = resolve_paths(args.paths)
    missing = check_missing(paths)
    if missing:
        for path in missing:
            print(f"ERROR: missing audit target: {path}", file=sys.stderr)
        return 2

    audits = sort_audits(audit_path(path) for path in paths)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(build_report(audits), encoding="utf-8")

    if args.emit_json:
        print(build_json(audits))
    elif not args.output:
        print(build_report(audits))

    if args.check_class:
        threshold = CLASS_RANK[args.check_class]
        has_blocking = any(
            CLASS_RANK[finding.classification] <= threshold
            for audit in audits
            for finding in audit.findings
        )
        if has_blocking:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
