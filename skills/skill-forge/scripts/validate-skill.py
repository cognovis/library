#!/usr/bin/env python3
"""
Validate a Claude Code skill (SKILL.md) for EXTRACTABLE_CODE violations and
judge-layer action_boundary shape.

Detects executable workflow logic embedded in skill body that should live
in bundled scripts instead. Mirrors the agent-side rule enforced by
skills/agent-forge/scripts/validate-agent.py.

See: skills/skill-forge/references/skill-script-first.md
     core/contracts/execution-result.schema.json

Usage:
    python3 validate-skill.py <skill-path>
    python3 validate-skill.py <skill-path> --strict

Arguments:
    skill-path   Path to SKILL.md file or skill directory (containing SKILL.md)

Options:
    --strict     Treat ADVISORY findings as BLOCKING (exit 1 if any advisory)

Exit codes:
    0  No findings (or advisory-only in non-strict mode)
    1  BLOCKING finding present (or any finding in --strict mode)
    2  File not found / parse error
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency fallback
    yaml = None


class SkillValidator:
    """Validator for Claude Code SKILL.md files — EXTRACTABLE_CODE enforcement."""

    FENCED_CODE_RE = re.compile(
        r"```(?P<lang>bash|sh|zsh|python)\s*\n(?P<body>.*?)```",
        re.IGNORECASE | re.DOTALL,
    )

    # Tool-ish keywords for verbal pipeline heuristic
    VERBAL_PIPELINE_KEYWORDS = {
        "bash", "python", "run", "grep", "query", "search", "parse",
        "store", "call", "execute", "scan", "read", "write", "check", "send",
    }
    ACTION_BOUNDARY_REQUIRED_FIELDS = {
        "risk_class",
        "effect_type",
        "proposal_schema",
        "judge",
        "requires_mandate",
    }
    ACTION_BOUNDARY_RISK_CLASSES = {
        "read-only",
        "reversible-write",
        "external-side-effect",
        "high-risk",
    }
    ACTION_BOUNDARY_EFFECT_TYPES = {
        "filesystem",
        "network",
        "financial",
        "messaging",
        "credential",
        "other",
    }
    SIDE_EFFECT_TOOL_RE = re.compile(r"\b(?:Write|Edit|Bash|MultiEdit)\b")
    MCP_WRITE_TOOL_RE = re.compile(
        r"\bmcp__[A-Za-z0-9_]*(?:write|create|update|delete|send|post|publish|"
        r"push|merge|commit|mutate|insert|upsert|grant|rotate)",
        re.IGNORECASE,
    )
    PROPOSAL_SCHEMA_RE = re.compile(
        r"^standard://[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*/"
        r"proposals/[A-Za-z0-9_.\-]+\.v[0-9]+$"
    )

    def __init__(self, skill_path: Path, strict: bool = False):
        self.skill_path = skill_path
        self.strict = strict
        self.blocking: list[str] = []
        self.advisory: list[str] = []
        self.body = ""
        self.frontmatter_text = ""
        self.frontmatter: dict[str, object] = {}
        self.display_name = ""

    def validate(self) -> tuple[bool, bool]:
        """
        Run all validations.

        Returns:
            (ok, load_failed) where:
            - load_failed is True if the skill could not be loaded (fatal error)
            - ok is True if no BLOCKING findings (and no advisory in strict mode)
        """
        if not self._load_skill():
            return False, True

        self._check_extractable_code()
        self._check_plugin_paths()
        self._check_action_boundary()

        if self.strict:
            ok = len(self.blocking) == 0 and len(self.advisory) == 0
        else:
            ok = len(self.blocking) == 0
        return ok, False

    def _load_skill(self) -> bool:
        """Resolve and load SKILL.md. Returns False on fatal errors."""
        path = self.skill_path

        # If given a directory, look for SKILL.md inside
        if path.is_dir():
            skill_file = path / "SKILL.md"
            if not skill_file.exists():
                print(f"Error: No SKILL.md found in {path}", file=sys.stderr)
                return False
            path = skill_file

        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            return False

        self.display_name = path.name if path.is_file() else path.parent.name

        try:
            content = path.read_text()
        except Exception as exc:
            print(f"Error: Failed to read {path}: {exc}", file=sys.stderr)
            return False

        # Normalize line endings and strip BOM so frontmatter detection is reliable
        content = content.lstrip("﻿").replace("\r\n", "\n")

        # Strip YAML frontmatter (--- ... ---)
        if content.startswith("---\n"):
            end_match = re.search(r"\n---\n", content[4:])
            if end_match:
                self.frontmatter_text = content[4:4 + end_match.start()].strip()
                try:
                    self.frontmatter = self._parse_frontmatter(self.frontmatter_text)
                except ValueError as exc:
                    print(
                        f"Error: Invalid YAML frontmatter in {path}: {exc}",
                        file=sys.stderr,
                    )
                    return False
                self.body = content[4 + end_match.end():].strip()
            else:
                # No closing ---, treat entire content as body
                self.body = content.strip()
        else:
            self.body = content.strip()

        return True

    @classmethod
    def _parse_frontmatter(cls, text: str) -> dict[str, object]:
        """Parse frontmatter as YAML, with a conservative fallback parser."""
        if yaml is not None:
            try:
                parsed_yaml = yaml.safe_load(text)
            except Exception as exc:
                raise ValueError(str(exc)) from exc
            if parsed_yaml is None:
                return {}
            if not isinstance(parsed_yaml, dict):
                raise ValueError("frontmatter must be a YAML mapping")
            return parsed_yaml

        parsed: dict[str, object] = {}
        parent_key: str | None = None

        for raw_line in text.splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue

            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            raw_value = value.strip()
            value = cls._clean_scalar(raw_value)

            if indent == 0:
                cls._validate_fallback_scalar(key, raw_value)
                if value == "":
                    parsed[key] = {}
                    parent_key = key
                else:
                    parsed[key] = value
                    parent_key = None
                continue

            if parent_key and isinstance(parsed.get(parent_key), dict):
                cls._validate_fallback_scalar(key, raw_value)
                parsed[parent_key][key] = value

        return parsed

    @staticmethod
    def _validate_fallback_scalar(key: str, value: str) -> None:
        """Catch common invalid unquoted flow-looking scalar values."""
        if not value:
            return
        if value.startswith(("\"", "'")):
            return
        if value.startswith("[") and (not value.endswith("]") or "] [" in value):
            raise ValueError(
                f"`{key}` has an unquoted bracketed scalar; quote values such as "
                '`"[subcommand] [args]"`'
            )

    @staticmethod
    def _clean_scalar(value: str) -> str:
        """Strip quotes and inline comments from a simple YAML scalar."""
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        return value

    def _check_extractable_code(self) -> None:
        """Detect EXTRACTABLE_CODE patterns in the skill body."""
        script_hint = (
            "Move to scripts/<name>.py and use "
            "core/contracts/execution-result.schema.json for multi-field outputs"
        )
        script_hint_advisory = "Consider extracting to scripts/<name>.py"

        # --- Pattern 1: Fenced code blocks ---
        for match in self.FENCED_CODE_RE.finditer(self.body):
            lang = match.group("lang").lower()
            block = match.group("body")
            real_lines = [
                line for line in block.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            line_count = len(real_lines)

            if lang == "python" and line_count > 3:
                self.blocking.append(
                    f"EXTRACTABLE_CODE: {line_count}-line Python block in skill body\n"
                    f"    → {script_hint}"
                )
            elif lang in {"bash", "sh", "zsh"} and line_count > 5:
                self.blocking.append(
                    f"EXTRACTABLE_CODE: {line_count}-line shell block in skill body\n"
                    f"    → {script_hint}"
                )
            elif lang in {"bash", "sh", "zsh"} and self._looks_like_pipeline(block):
                self.advisory.append(
                    "EXTRACTABLE_CODE: inline multi-step shell pipeline in skill body\n"
                    f"    → {script_hint_advisory}"
                )

        # --- Pattern 2: Verbal multi-step pipelines ---
        if self._looks_like_verbal_pipeline(self.body):
            self.advisory.append(
                "EXTRACTABLE_CODE: verbal multi-step pipeline (ordered list with 4+ "
                "items containing tool/action keywords)\n"
                f"    → {script_hint_advisory}"
            )

        # --- Pattern 3: Inline python -c ---
        if re.search(r"\b(?:python|python3|uv run python)\s+-c\b", self.body):
            self.advisory.append(
                "EXTRACTABLE_CODE: inline Python -c invocation in skill body\n"
                f"    → {script_hint_advisory}"
            )

    # Known plugin folders in this repo — if a new plugin is added, update this list.
    PLUGIN_FOLDERS = (
        "beads-workflow", "core", "dev-tools", "meta", "infra",
        "business", "content", "medical", "open-brain",
    )
    PLUGIN_PATH_RE = re.compile(
        r"\b(" + "|".join(PLUGIN_FOLDERS) + r")"
        r"/(scripts|hooks|lib)/"
        r"[A-Za-z0-9_./\-]+\.(py|sh)\b"
    )

    def _check_plugin_paths(self) -> None:
        """Flag CWD-relative plugin script paths inside fenced bash/python code blocks.

        Paths like `beads-workflow/scripts/claim-bead.py` only resolve when CWD is
        the dev repo. In worktrees or consumer projects they break with ENOENT.
        Use `${CLAUDE_PLUGIN_ROOT}/…` so Claude Code resolves the installed plugin
        root regardless of CWD. See CCP-b9d for the regression this prevents.
        """
        hint = (
            'Use "${CLAUDE_PLUGIN_ROOT}/<subdir>/<script>" instead. '
            "CWD-relative paths break in worktrees and consumer projects."
        )
        for match in self.FENCED_CODE_RE.finditer(self.body):
            lang = match.group("lang").lower()
            if lang not in {"bash", "sh", "zsh", "python"}:
                continue
            block = match.group("body")
            for pmatch in self.PLUGIN_PATH_RE.finditer(block):
                start = pmatch.start()
                # Skip if the match is itself the tail of an absolute path
                # (preceded by `/`) — e.g. `/Users/.../beads-workflow/scripts/x.py`.
                if start > 0 and block[start - 1] == "/":
                    continue
                # Skip if preceded by ${CLAUDE_PLUGIN_ROOT}/ (with or without braces).
                window = block[max(0, start - 30):start]
                if ("${CLAUDE_PLUGIN_ROOT}/" in window
                        or "$CLAUDE_PLUGIN_ROOT/" in window):
                    continue
                self.blocking.append(
                    f"PLUGIN_PATH: CWD-relative `{pmatch.group(0)}`\n"
                    f"    → {hint}"
                )

    def _check_action_boundary(self) -> None:
        """Validate judge-layer action_boundary frontmatter shape."""
        boundary = self.frontmatter.get("action_boundary")

        if boundary is None:
            if self._declares_side_effect_tools():
                self.advisory.append(
                    "ACTION_BOUNDARY: side-effecting tool declaration without "
                    "`action_boundary` frontmatter\n"
                    "    → Add risk_class/effect_type/proposal_schema/judge/"
                    "requires_mandate before the skill performs side effects"
                )
            return

        if not isinstance(boundary, dict):
            self.blocking.append(
                "ACTION_BOUNDARY: `action_boundary` must be a mapping with "
                "risk_class/effect_type/proposal_schema/judge/requires_mandate"
            )
            return

        if "class" in boundary:
            self.blocking.append(
                "ACTION_BOUNDARY: obsolete `class` key found\n"
                "    → Use `risk_class` instead"
            )

        missing = sorted(self.ACTION_BOUNDARY_REQUIRED_FIELDS - set(boundary))
        if missing:
            self.blocking.append(
                "ACTION_BOUNDARY: missing required field(s): "
                + ", ".join(missing)
            )

        risk_class = str(boundary.get("risk_class", ""))
        if risk_class and risk_class not in self.ACTION_BOUNDARY_RISK_CLASSES:
            self.blocking.append(
                "ACTION_BOUNDARY: invalid risk_class "
                f"`{risk_class}`; expected one of "
                + ", ".join(sorted(self.ACTION_BOUNDARY_RISK_CLASSES))
            )

        effect_type = str(boundary.get("effect_type", ""))
        if effect_type and effect_type not in self.ACTION_BOUNDARY_EFFECT_TYPES:
            self.blocking.append(
                "ACTION_BOUNDARY: invalid effect_type "
                f"`{effect_type}`; expected one of "
                + ", ".join(sorted(self.ACTION_BOUNDARY_EFFECT_TYPES))
            )

        proposal_schema = str(boundary.get("proposal_schema", ""))
        if proposal_schema and not self.PROPOSAL_SCHEMA_RE.fullmatch(proposal_schema):
            self.blocking.append(
                "ACTION_BOUNDARY: proposal_schema must be a standard proposal URI "
                "such as `standard://judge-layer/proposals/action-proposal.v1`"
            )

        judge = str(boundary.get("judge", ""))
        if judge and not judge.startswith("agent://"):
            self.blocking.append(
                "ACTION_BOUNDARY: judge must be an agent URI such as "
                "`agent://judge-default`"
            )

        requires_mandate = str(boundary.get("requires_mandate", "")).lower()
        if risk_class in {"external-side-effect", "high-risk"} and requires_mandate != "true":
            self.blocking.append(
                "ACTION_BOUNDARY: external-side-effect and high-risk skills "
                "must set `requires_mandate: true`"
            )

    def _declares_side_effect_tools(self) -> bool:
        """Detect explicit side-effect-capable tool declarations in frontmatter."""
        tool_text = self._tool_declaration_text()
        return bool(
            self.SIDE_EFFECT_TOOL_RE.search(tool_text)
            or self.MCP_WRITE_TOOL_RE.search(tool_text)
        )

    def _tool_declaration_text(self) -> str:
        """Return only tools/allowed-tools frontmatter blocks."""
        blocks: list[str] = []
        capture = False

        for raw_line in self.frontmatter_text.splitlines():
            stripped = raw_line.strip()
            indent = len(raw_line) - len(raw_line.lstrip(" "))

            if indent == 0 and ":" in stripped:
                key = stripped.split(":", 1)[0].strip()
                capture = key in {"tools", "allowed-tools"}

            if capture:
                blocks.append(raw_line)

        return "\n".join(blocks)

    @staticmethod
    def _looks_like_pipeline(block: str) -> bool:
        """Heuristic: shell block acting as a small program (pipeline markers).

        Counts total occurrences of pipeline markers (not just presence) so that
        a single line like `find ... | grep ... | head` scores 3+ hits.
        """
        # Patterns where we count ALL occurrences (e.g. multiple |)
        multi_count_patterns = [
            r"(?<!\|)\|(?!\|)",  # pipe operator — exclude || (logical OR)
            r"\$\(",             # command substitution
        ]
        # Patterns where presence alone counts (count once per tool)
        presence_patterns = [
            r"\bjq\b",
            r"\bgrep\b",
            r"\bsed\b",
            r"\bawk\b",
            r"\bsqlite3\b",
            r"\bcmux\b",
            r"\b(?:python|python3|uv run python)\s+-c\b",
            r"2>&1",
        ]
        hits = sum(len(re.findall(pattern, block)) for pattern in multi_count_patterns)
        hits += sum(1 for pattern in presence_patterns if re.search(pattern, block))
        real_lines = [
            line for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        # Flag if 3+ pipeline markers total (pipes + tools),
        # which catches both single-line chained pipelines and multi-step blocks.
        # Also flag lighter blocks if they span 4+ real lines and have 2+ hits.
        return hits >= 3 or (len(real_lines) >= 4 and hits >= 2)

    def _looks_like_verbal_pipeline(self, body: str) -> bool:
        """
        Heuristic: ordered list with 4+ consecutive items each containing
        at least one tool/action keyword.
        """
        ordered_item_re = re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE)
        items = ordered_item_re.findall(body)

        # Find runs of 4+ consecutive keyword-bearing items
        run = 0
        for item in items:
            words = set(re.findall(r"\b[a-z]+\b", item.lower()))
            if words & self.VERBAL_PIPELINE_KEYWORDS:
                run += 1
                if run >= 4:
                    return True
            else:
                run = 0
        return False

    def print_report(self) -> None:
        """Print findings to stdout in the canonical format."""
        if not self.blocking and not self.advisory:
            return

        # Findings are stored with an explicit category tag, e.g. "EXTRACTABLE_CODE: …"
        # or "PLUGIN_PATH: …". The print format prepends the BLOCKING/ADVISORY marker.
        for finding in self.blocking:
            print(f"[BLOCKING] {finding}")
        for finding in self.advisory:
            print(f"[ADVISORY] {finding}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate a SKILL.md file for EXTRACTABLE_CODE violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 validate-skill.py meta/skills/my-skill/
  python3 validate-skill.py meta/skills/my-skill/SKILL.md
  python3 validate-skill.py meta/skills/my-skill/ --strict

Exit codes:
  0  No findings (or advisory-only in non-strict mode)
  1  BLOCKING finding (or any finding in --strict mode)
  2  File not found / parse error
        """,
    )
    parser.add_argument(
        "skill_path",
        type=Path,
        help="Path to SKILL.md file or skill directory",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat ADVISORY findings as BLOCKING (exit 1 if any advisory)",
    )

    args = parser.parse_args()

    validator = SkillValidator(args.skill_path, strict=args.strict)

    ok, load_failed = validator.validate()
    if load_failed:
        sys.exit(2)

    validator.print_report()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
