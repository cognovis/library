#!/usr/bin/env python3
"""Inventory Codex compatibility across the repo's skill fleet."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_FILENAMES = ("SKILL.md", "skill.md")
EXCLUDED_PATH_PARTS = {
    ".agents",
    ".claude",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "fixtures",
    "tests",
}


@dataclass(frozen=True)
class SkillRecord:
    name: str
    source_dir: str
    skill_file: str
    codex_support: str
    codex_support_reason: str


@dataclass(frozen=True)
class Finding:
    severity: str
    detail: str


@dataclass(frozen=True)
class ScanResult:
    name: str
    source_dir: str
    status: str
    findings: list[Finding]
    codex_support_reason: str


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the small subset of YAML frontmatter needed for this scanner."""
    if not text.startswith("---\n"):
        return {}

    end = text.find("\n---\n", 4)
    if end == -1:
        return {}

    frontmatter = text[4:end].splitlines()
    parsed: dict[str, str] = {}
    index = 0
    while index < len(frontmatter):
        line = frontmatter[index]
        if not line.strip() or line.lstrip().startswith("#") or line.startswith((" ", "\t")):
            index += 1
            continue

        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            index += 1
            continue

        key, raw_value = match.groups()
        raw_value = raw_value.strip()
        if raw_value in {"|", "|-", ">", ">-"}:
            index += 1
            block: list[str] = []
            while index < len(frontmatter):
                next_line = frontmatter[index]
                if next_line.startswith((" ", "\t")):
                    block.append(next_line.lstrip())
                    index += 1
                    continue
                if not next_line.strip():
                    block.append("")
                    index += 1
                    continue
                break

            parsed[key] = (
                "\n".join(block).strip()
                if raw_value.startswith("|")
                else _normalize_ws(" ".join(item for item in block if item.strip()))
            )
            continue

        parsed[key] = raw_value.strip("\"'")
        index += 1

    return parsed


def _codex_support(frontmatter: dict[str, str]) -> tuple[str, str]:
    raw_value = frontmatter.get("codex-support", "enabled").strip().lower()
    reason = _normalize_ws(frontmatter.get("codex-support-reason", ""))
    if raw_value in {"disabled", "false", "cc-only", "claude-only"}:
        return "disabled", reason or "Marked as intentionally excluded from Codex export."
    return "enabled", reason


def discover_skills(repo_root: Path = REPO_ROOT) -> list[SkillRecord]:
    """Discover source skills in the current catalog layout."""
    discovered: list[SkillRecord] = []
    seen_names: dict[str, str] = {}
    base = repo_root / "skills"
    if not base.is_dir():
        return []

    skill_files = sorted(
        candidate
        for candidate in base.rglob("*")
        if candidate.is_file() and candidate.name in SKILL_FILENAMES
    )
    for skill_file in skill_files:
        relative = skill_file.relative_to(repo_root)
        if any(part in EXCLUDED_PATH_PARTS for part in relative.parts):
            continue

        skill_dir = skill_file.parent
        skill_name = skill_dir.name
        existing = seen_names.get(skill_name)
        if existing is not None:
            raise RuntimeError(
                f"Duplicate skill name '{skill_name}' in {existing} and {skill_dir.relative_to(repo_root)}"
            )

        frontmatter = _parse_frontmatter(skill_file.read_text(encoding="utf-8", errors="ignore"))
        codex_support, codex_reason = _codex_support(frontmatter)
        record = SkillRecord(
            name=skill_name,
            source_dir=str(skill_dir.relative_to(repo_root)),
            skill_file=str(relative),
            codex_support=codex_support,
            codex_support_reason=codex_reason,
        )
        discovered.append(record)
        seen_names[skill_name] = record.source_dir

    return sorted(discovered, key=lambda record: record.name)


NEEDS_FIX_PATTERNS = (
    (
        "blocking",
        "Named MCP tool invocation in portable SKILL.md",
        re.compile(r"mcp__[\w-]+"),
    ),
    (
        "blocking",
        "Claude-specific AskUserQuestion reference",
        re.compile(r"\bAskUserQuestion\b"),
    ),
    (
        "blocking",
        "Claude subagent invocation syntax",
        re.compile(r"Agent\(subagent_type=|subagent_type="),
    ),
    (
        "blocking",
        "Claude template variable $ARGUMENTS",
        re.compile(r"\$ARGUMENTS"),
    ),
    (
        "blocking",
        "Claude home path reference",
        re.compile(r"~\/\.claude\/|(?:^|[\s`])\.claude\/"),
    ),
    (
        "blocking",
        "Harness-specific slash-command syntax",
        re.compile(r"^/[a-z][a-z0-9-]+(?:\s|$)", re.MULTILINE),
    ),
    (
        "blocking",
        "Harness-specific agent name in portable core",
        re.compile(r"\bbead-orchestrator\b|\bsession-close\b"),
    ),
    (
        "advisory",
        "Claude-only allowed-tools frontmatter",
        re.compile(r"^allowed-tools:\s*$", re.MULTILINE),
    ),
    (
        "advisory",
        "Named Claude tool identifiers in imperative wording",
        re.compile(
            r"\b(?:Use|Call)\s+(?:the\s+)?"
            r"(?:Read|Glob|Grep|Bash|Edit|Write|NotebookEdit|WebFetch|WebSearch|Task|TodoWrite)"
            r"(?:\s+tools?|\s+tool)?\b"
        ),
    ),
)


def classify_skill(record: SkillRecord) -> ScanResult:
    if record.codex_support == "disabled":
        return ScanResult(
            name=record.name,
            source_dir=record.source_dir,
            status="cc-only",
            findings=[],
            codex_support_reason=record.codex_support_reason,
        )

    content = (REPO_ROOT / record.skill_file).read_text(encoding="utf-8", errors="ignore")
    findings: list[Finding] = []
    for severity, detail, pattern in NEEDS_FIX_PATTERNS:
        if pattern.search(content):
            findings.append(Finding(severity=severity, detail=detail))

    status = "works-as-is" if not findings else "needs-fix"
    return ScanResult(
        name=record.name,
        source_dir=record.source_dir,
        status=status,
        findings=findings,
        codex_support_reason=record.codex_support_reason,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan all skills and classify them as works-as-is / needs-fix / cc-only for Codex."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--fail-on-needs-fix",
        action="store_true",
        help="Exit 1 when any skill is classified as needs-fix.",
    )
    parser.add_argument(
        "--skills",
        help="Comma-separated subset of skill names to scan. Default: full fleet.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    skill_filter = None
    if args.skills:
        skill_filter = [item.strip() for item in args.skills.split(",")]
        if any(not item for item in skill_filter):
            print("ERROR: empty skill name in --skills list", file=sys.stderr)
            raise SystemExit(2)

    records = discover_skills()
    records_by_name = {record.name: record for record in records}
    if skill_filter is not None:
        missing = [name for name in skill_filter if name not in records_by_name]
        if missing:
            print(f"ERROR: unknown skills: {', '.join(missing)}", file=sys.stderr)
            raise SystemExit(2)
        records = [records_by_name[name] for name in skill_filter]

    results = [classify_skill(record) for record in records]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        **asdict(result),
                        "findings": [asdict(finding) for finding in result.findings],
                    }
                    for result in results
                ],
                indent=2,
            )
        )
    else:
        for result in results:
            if result.status == "works-as-is":
                print(f"PASS       {result.name:<24} {result.source_dir}")
            elif result.status == "cc-only":
                print(f"CC_ONLY    {result.name:<24} {result.codex_support_reason}")
            else:
                details = "; ".join(f"{finding.severity}: {finding.detail}" for finding in result.findings)
                print(f"NEEDS_FIX  {result.name:<24} {details}")

        passes = sum(result.status == "works-as-is" for result in results)
        needs_fix = sum(result.status == "needs-fix" for result in results)
        cc_only = sum(result.status == "cc-only" for result in results)
        print("")
        print(f"Summary: pass={passes} needs-fix={needs_fix} cc-only={cc_only}")

    if args.fail_on_needs_fix and any(result.status == "needs-fix" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
