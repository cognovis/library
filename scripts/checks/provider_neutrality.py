#!/usr/bin/env python3
"""Mechanical proof that core modules carry no provider knowledge (CL-coif AC4).

ADR-0011 makes one structural promise: heterogeneous providers are reached
through a declared capability contract, and the resolver, cache, and Workspace
layers contain **no provider-specific branch**. That promise decays quietly.
The first awkward provider tempts one conditional, the conditional is reviewed
once and never again, and a year later the "generic" contract is a fiction with
three special cases.

This check is why the promise is testable. It fails CI, not a review.

Four violation classes are detected, in identifiers, string literals, and
comments alike:

| Kind | What it catches |
|---|---|
| `provider-name` | A named provider or hosting service, including inside an identifier such as `resolve_github_url` |
| `provider-kind-conditional` | A `provider_kind` identifier, a provider-kind literal, or a branch on a legacy distribution-mechanism value |
| `upstream-url` | Any concrete upstream URL |
| `provider-host-literal` | A domain-shaped literal, which catches providers no allowlist could name in advance |

Comments count. A comment that claims a core module knows about a hosting
service is exactly the drift this check exists to catch, and exempting comments
would let the knowledge live one edit away from the code.

**What this check does not claim.** It is a tripwire over declared boundaries,
not a proof of impossibility. A sufficiently indirect branch — a provider kind
imported as a constant and compared through an alias — can still evade it. Two
things keep that honest rather than hollow:

- `LEGACY_PROVIDER_MODULES` names modules that *do* carry provider knowledge
  today, with a recorded baseline. Their count may fall, never rise, so the
  pre-ADR-0011 resolver cannot get worse while the new contract is built beside
  it, and the report never lets a clean core imply a clean repository.
- The report states both facts explicitly, so nobody reads "PASS" as more than
  it is.

Usage:
    uv run python scripts/checks/provider_neutrality.py
    uv run python scripts/checks/provider_neutrality.py --output artifact.json

Exit codes:
    0 — core is clean and no legacy module exceeds its baseline
    1 — a core finding, a legacy regression, or a missing scanned module
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

#: Legacy `marketplace.type` distribution mechanisms. A branch on one of these
#: is a provider-kind branch wearing the old field's name. They are matched as
#: whole string literals only: `"git"` as a substring appears in ordinary prose
#: such as "git rev-parse", and flagging that would train readers to ignore the
#: check.
LEGACY_TYPE_LITERALS: frozenset[str] = frozenset({"git", "skills-sh", "http-tarball"})

#: The identifier through which a provider-kind branch would be written.
PROVIDER_KIND_IDENTIFIER = "provider_kind"

#: Modules that legitimately carry provider knowledge today. They are the
#: pre-ADR-0011 resolution path that slice 6 (`CL-mvet`) replaces. The baseline
#: is a ratchet: it may fall, never rise.
LEGACY_PROVIDER_MODULES: dict[str, int] = {
    # 33 findings on 2026-08-08: hard-coded hosting-service URLs, host literals,
    # a branch on the legacy `type` value, and provider-named identifiers in
    # `resolve_marketplace_source` and its helpers. Slice 6 (`CL-mvet`) routes
    # this path through the adapters and drives the number down.
    "scripts/lib/source.py": 33,
}

_URL_RE = re.compile(r"(?:https?|ftp|git\+https?)://[^\s'\"`)]+|git@[\w.-]+:[\w./-]+")
#: A domain-shaped literal. Deliberately restricted to common TLDs so that
#: `file.py` or `item.md` is not read as a hostname.
_DOMAIN_RE = re.compile(
    r"(?<![\w.-])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*"
    r"\.(?:com|org|net|io|dev|sh|ai|co|app|cloud|xyz|me|gg|to)(?![\w-])",
    re.IGNORECASE,
)
_STRING_LITERAL_RE = re.compile(r"^[rbufRBUF]*('''|\"\"\"|'|\")(?P<body>.*)\1$", re.DOTALL)
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


def _string_body(text: str) -> str | None:
    """The content of a string literal token, or None when it is not one."""
    match = _STRING_LITERAL_RE.match(text)
    return match.group("body") if match else None


def _scan_text_tokens(path: str, source: str) -> list[Finding]:
    """Scan identifiers, string literals, and comments.

    Identifiers are scanned for provider names because `resolve_github_url` is
    provider knowledge whether or not the word appears in a string.
    """
    findings: list[Finding] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:  # pragma: no cover - a syntax error is reported by AST
        tokens = []
    for token in tokens:
        text = token.string
        line = token.start[0]

        if token.type == tokenize.NAME:
            for name in PROVIDER_NAME_TOKENS:
                if name.replace("-", "_") in text.lower() or name in text.lower():
                    findings.append(
                        Finding(path, line, "provider-name", name, f"identifier {text}")
                    )
            continue

        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue

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
        body = _string_body(text) if token.type == tokenize.STRING else None
        if body is not None and body in LEGACY_TYPE_LITERALS:
            findings.append(
                Finding(path, line, "provider-kind-conditional", body, _excerpt(text))
            )
        for match in _URL_RE.finditer(text):
            findings.append(
                Finding(path, line, "upstream-url", match.group(0), _excerpt(text))
            )
        for match in _DOMAIN_RE.finditer(text):
            findings.append(
                Finding(path, line, "provider-host-literal", match.group(0), _excerpt(text))
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


@dataclass(frozen=True)
class LegacyStatus:
    """One legacy module measured against its recorded baseline."""

    path: str
    baseline: int
    observed: int

    @property
    def regressed(self) -> bool:
        return self.observed > self.baseline

    @property
    def improved(self) -> bool:
        return self.observed < self.baseline

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "baseline": self.baseline,
            "observed": self.observed,
            "state": "regressed" if self.regressed else ("improved" if self.improved else "held"),
        }


def scan_legacy(
    repo_root: Path, baselines: dict[str, int] | None = None
) -> list[LegacyStatus]:
    """Measure the declared legacy provider-aware modules against their baseline.

    These modules are *expected* to contain provider knowledge: they are the
    pre-ADR-0011 path. What is not expected is for them to gain more of it while
    the generic contract is being built beside them.
    """
    statuses: list[LegacyStatus] = []
    for relative, baseline in (baselines or LEGACY_PROVIDER_MODULES).items():
        path = repo_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"legacy provider module is missing: {path}")
        observed = len(scan_source(relative, path.read_text(encoding="utf-8")))
        statuses.append(LegacyStatus(path=relative, baseline=baseline, observed=observed))
    return statuses


def build_report(
    repo_root: Path,
    findings: Sequence[Finding],
    legacy: Sequence[LegacyStatus] = (),
) -> dict[str, object]:
    regressions = [status for status in legacy if status.regressed]
    return {
        "schema": SCHEMA,
        "bead_id": BEAD_ID,
        "repo_root": str(repo_root),
        "scanned": list(CORE_MODULES),
        "violation_kinds": [
            "provider-name",
            "provider-kind-conditional",
            "upstream-url",
            "provider-host-literal",
        ],
        "result": "fail" if (findings or regressions) else "pass",
        "findings": [finding.to_dict() for finding in findings],
        "legacy_provider_modules": [status.to_dict() for status in legacy],
        "scope_note": (
            "A pass means the named core modules carry no provider knowledge and "
            "no declared legacy module exceeds its baseline. It is not a claim "
            "about every module in the repository."
        ),
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
        legacy = scan_legacy(repo_root)
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}")
        return 1

    report = build_report(repo_root, findings, legacy)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    regressions = [status for status in legacy if status.regressed]

    if findings:
        print(f"FAIL: {len(findings)} provider-knowledge finding(s) in core modules")
        for finding in findings:
            print(f"  {finding.render()}")
        print(
            "\nCore modules consume the normalized inventory only. Move provider "
            "knowledge into a provider adapter under scripts/lib/providers/."
        )
    if regressions:
        print(f"FAIL: {len(regressions)} legacy module(s) gained provider knowledge")
        for status in regressions:
            print(f"  {status.path}: {status.observed} findings, baseline {status.baseline}")
        print(
            "\nThese modules are the pre-ADR-0011 path and are being replaced, not "
            "extended. Add new provider knowledge to an adapter instead."
        )
    if findings or regressions:
        return 1

    print(f"PASS: no provider knowledge in {len(CORE_MODULES)} core module(s)")
    for relative in CORE_MODULES:
        print(f"  {relative}")
    if legacy:
        print("Declared legacy provider-aware modules (baseline is a ratchet):")
        for status in legacy:
            note = " (improved — lower the baseline)" if status.improved else ""
            print(f"  {status.path}: {status.observed}/{status.baseline}{note}")
    print(
        "This pass covers the modules named above. It is not a claim about every "
        "module in the repository."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
