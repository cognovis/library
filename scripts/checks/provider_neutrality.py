#!/usr/bin/env python3
"""Mechanical proof that core modules carry no provider knowledge (CL-coif AC4).

ADR-0011 makes one structural promise: heterogeneous providers are reached
through a declared capability contract, and the resolver, cache, and Workspace
layers contain **no provider-specific branch**. That promise decays quietly.
The first awkward provider tempts one conditional, the conditional is reviewed
once and never again, and a year later the "generic" contract is a fiction with
three special cases.

This check is why the promise is testable. It fails CI, not a review.

Three violation classes are detected:

| Kind | What it catches |
|---|---|
| `provider-name` | A provider or hosting-service name in code, string, or comment |
| `provider-kind-conditional` | A `provider_kind` identifier or a provider-kind literal |
| `upstream-url` | Any concrete upstream URL |

Comments count. A comment that claims a core module knows about a hosting
service is exactly the drift this check exists to catch, and exempting comments
would let the knowledge live one edit away from the code.

Usage:
    uv run python scripts/checks/provider_neutrality.py
    uv run python scripts/checks/provider_neutrality.py --output artifact.json

Exit codes:
    0 — no findings
    1 — at least one finding, or a scanned module is missing
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

SCHEMA = "cognovis.provider-neutrality.v1"
BEAD_ID = "CL-coif"

#: The modules ADR-0011 names as consumers of the normalized inventory only.
CORE_MODULES: tuple[str, ...] = (
    "scripts/lib/resolver.py",
    "scripts/lib/cache.py",
    "scripts/lib/workspace.py",
)

#: Provider and hosting-service names. A core module has no business naming one.
PROVIDER_NAME_TOKENS: tuple[str, ...] = (
    "github",
    "gitlab",
    "bitbucket",
    "sourcehut",
    "codeberg",
    "huggingface",
    "npmjs",
    "mattpocock",
    "disler",
    "executive-circle",
    "skills-sh",
    "skills.sh",
)

#: The provider kinds of ADR-0011 `Provider kinds`, as literals.
PROVIDER_KIND_TOKENS: tuple[str, ...] = (
    "git-repo",
    "git-org",
    "mcp-content",
    "hosted-index",
)

#: The identifier through which a provider-kind branch would be written.
PROVIDER_KIND_IDENTIFIER = "provider_kind"

_URL_RE = re.compile(r"(?:https?|ftp|git\+https?)://[^\s'\"`)]+|git@[\w.-]+:[\w./-]+")
_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _token_pattern(token: str) -> re.Pattern[str]:
    pattern = _WORD_BOUNDARY_CACHE.get(token)
    if pattern is None:
        pattern = re.compile(rf"(?<![\w-]){re.escape(token)}(?![\w-])", re.IGNORECASE)
        _WORD_BOUNDARY_CACHE[token] = pattern
    return pattern


@dataclass(frozen=True)
class Finding:
    """One provider-knowledge leak, located precisely enough to fix."""

    path: str
    line: int
    kind: str
    token: str
    excerpt: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.token!r} in {self.excerpt!r}"

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "token": self.token,
            "excerpt": self.excerpt,
        }


def _excerpt(text: str, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."


def _scan_text_tokens(path: str, source: str) -> list[Finding]:
    """Scan string literals and comments for provider names, kinds, and URLs."""
    findings: list[Finding] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:  # pragma: no cover - a syntax error is reported by AST
        tokens = []
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        text = token.string
        line = token.start[0]
        for name in PROVIDER_NAME_TOKENS:
            if _token_pattern(name).search(text):
                findings.append(
                    Finding(path, line, "provider-name", name, _excerpt(text))
                )
        for kind in PROVIDER_KIND_TOKENS:
            if _token_pattern(kind).search(text):
                findings.append(
                    Finding(path, line, "provider-kind-conditional", kind, _excerpt(text))
                )
        if PROVIDER_KIND_IDENTIFIER in text:
            findings.append(
                Finding(
                    path,
                    line,
                    "provider-kind-conditional",
                    PROVIDER_KIND_IDENTIFIER,
                    _excerpt(text),
                )
            )
        for match in _URL_RE.finditer(text):
            findings.append(
                Finding(path, line, "upstream-url", match.group(0), _excerpt(text))
            )
    return findings


def _scan_identifiers(path: str, source: str) -> list[Finding]:
    """Scan the AST for the `provider_kind` identifier in any position.

    A branch can be written without any provider literal at all
    (`if entry.provider_kind == expected:`). The identifier is the tell.
    """
    findings: list[Finding] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - unparsable core module
        return [
            Finding(path, exc.lineno or 0, "unparsable", str(exc.msg), _excerpt(source[:120]))
        ]
    for node in ast.walk(tree):
        name: str | None = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.arg):
            name = node.arg
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        if name and PROVIDER_KIND_IDENTIFIER in name:
            findings.append(
                Finding(
                    path,
                    getattr(node, "lineno", 0),
                    "provider-kind-conditional",
                    name,
                    "identifier",
                )
            )
    return findings


def _deduplicate(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, int, str, str]] = set()
    ordered: list[Finding] = []
    for finding in findings:
        key = (finding.path, finding.line, finding.kind, finding.token)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(finding)
    return sorted(ordered, key=lambda item: (item.path, item.line, item.kind, item.token))


def scan_source(path: str, source: str) -> list[Finding]:
    """Scan one module's source text for provider knowledge."""
    return _deduplicate([*_scan_text_tokens(path, source), *_scan_identifiers(path, source)])


def scan_paths(paths: Sequence[Path], *, relative_to: Path | None = None) -> list[Finding]:
    """Scan the given files.

    Raises:
        FileNotFoundError: when a path does not exist. A renamed or deleted core
            module must fail the gate rather than shrink it silently.
    """
    findings: list[Finding] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"provider-neutrality target is missing: {path}")
        label = str(path.relative_to(relative_to)) if relative_to else str(path)
        findings.extend(scan_source(label, path.read_text(encoding="utf-8")))
    return _deduplicate(findings)


def scan_repository(repo_root: Path, modules: Sequence[str] = CORE_MODULES) -> list[Finding]:
    """Scan the declared core modules of one repository checkout."""
    return scan_paths([repo_root / relative for relative in modules], relative_to=repo_root)


def build_report(repo_root: Path, findings: Sequence[Finding]) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "bead_id": BEAD_ID,
        "repo_root": str(repo_root),
        "scanned": list(CORE_MODULES),
        "violation_kinds": ["provider-name", "provider-kind-conditional", "upstream-url"],
        "result": "fail" if findings else "pass",
        "findings": [finding.to_dict() for finding in findings],
    }


def _default_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "library.yaml").exists():
            return current
        current = current.parent
    return Path.cwd()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--output", default=None, help="write the typed artifact here")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else _default_repo_root()
    try:
        findings = scan_repository(repo_root)
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}")
        return 1

    report = build_report(repo_root, findings)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if findings:
        print(f"FAIL: {len(findings)} provider-knowledge finding(s) in core modules")
        for finding in findings:
            print(f"  {finding.render()}")
        print(
            "\nCore modules consume the normalized inventory only. Move provider "
            "knowledge into a provider adapter under scripts/lib/providers/."
        )
        return 1

    print(f"PASS: no provider knowledge in {len(CORE_MODULES)} core module(s)")
    for relative in CORE_MODULES:
        print(f"  {relative}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
