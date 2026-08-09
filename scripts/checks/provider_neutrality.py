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
#:
#: The rights, admission, and executable-admission gates (`CL-n7ex`) are listed
#: here even though they live under the adapter directory, which is otherwise
#: the sanctioned home for provider knowledge. They are core by function: they
#: decide what a scope may do with an item, and a gate that recognized a
#: provider by name could grant that provider a permission its recorded rights
#: never granted. Their location is a packaging fact; their neutrality is a
#: contract, so the check states it explicitly rather than inheriting the
#: adapter exemption.
#: The durable foreign cache (`CL-y5z4`) is listed for the same reason: cache
#: identity, the install transaction, the offline table, and the receipt store
#: decide what survives a source outage. A cache that recognized a source by
#: name could keep one source's bytes and discard another's under a rule nobody
#: wrote down, which is the failure the tuple key exists to make impossible.
CORE_MODULES: tuple[str, ...] = (
    "scripts/lib/resolver.py",
    "scripts/lib/cache.py",
    "scripts/lib/workspace.py",
    "scripts/lib/providers/rights.py",
    "scripts/lib/providers/admission.py",
    "scripts/lib/providers/executable_admission.py",
    "scripts/lib/providers/foreign_cache.py",
    "scripts/lib/providers/cache_transaction.py",
    "scripts/lib/providers/offline.py",
    "scripts/lib/providers/receipts.py",
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

#: Where the legacy fingerprint baseline lives. It is generated, committed, and
#: compared per finding identity — never by counting.
BASELINE_PATH = "scripts/checks/provider_neutrality_baseline.json"
BASELINE_SCHEMA = "cognovis.provider-neutrality-baseline.v1"

#: Directories whose modules are measured as legacy provider-aware code.
LEGACY_ROOTS: tuple[str, ...] = ("scripts/lib",)

#: Where provider knowledge **belongs**. Adapters are the sanctioned boundary,
#: so they are neither required to be clean nor recorded as debt. Measuring them
#: would turn the correct location for provider knowledge into a debt ledger and
#: make every new adapter look like a regression.
PROVIDER_ADAPTER_ROOTS: tuple[str, ...] = ("scripts/lib/providers",)

_URL_RE = re.compile(r"(?:https?|ftp|git\+https?)://[^\s'\"`)]+|git@[\w.-]+:[\w./-]+")
#: A domain-shaped literal. Restricted to a broad but closed TLD set so that
#: `file.py`, `item.md`, or `lib.providers.inventory` is not read as a hostname.
_TLDS = (
    "com|org|net|io|dev|sh|ai|co|app|cloud|xyz|me|gg|to|de|eu|fr|uk|ch|at|it|es|nl"
    "|se|no|dk|fi|pl|cz|ru|cn|jp|in|br|ca|au|us|tech|tools|works|page|site|network"
    "|systems|software|codes|run|build|team|space|store|online|live|blog|wiki|cc|tv"
)
_DOMAIN_RE = re.compile(
    r"(?<![\w.-])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*" rf"\.(?:{_TLDS})(?![\w-])",
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

    @property
    def fingerprint(self) -> str:
        """Line-independent identity of this finding.

        The baseline compares fingerprints, not counts. Counting cannot tell
        "an old leak was removed" from "a new leak was added", so a counted
        ratchet lets a module swap one provider branch for another and stay
        green -- which a reviewer demonstrated end to end.
        """
        return f"{self.kind}:{self.token.lower()}"

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


def _normalized_identifier(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _scan_ast(path: str, source: str) -> list[Finding]:
    """Scan the AST for identifiers and for every string value, f-strings included.

    Two reasons this exists beside the token scan:

    - A branch can be written without any provider literal at all
      (`if entry.provider_kind == expected:`), and with any casing
      (`PROVIDER_KIND`). The identifier is the tell.
    - Since PEP 701, an f-string is tokenized as `FSTRING_START`/`MIDDLE`/`END`
      rather than as a `STRING`, so a token-only scan silently ignores
      `f"https://host/{owner}/{repo}"` -- the single most idiomatic way to build
      an upstream URL. A reviewer demonstrated exactly that bypass against a
      poisoned copy of a core module, and this walk closes it on every Python
      version because the AST shape is unchanged.
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
        if name and PROVIDER_KIND_IDENTIFIER.replace("_", "") in _normalized_identifier(name):
            findings.append(
                Finding(
                    path,
                    getattr(node, "lineno", 0),
                    "provider-kind-conditional",
                    name,
                    "identifier",
                )
            )

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            findings.extend(
                _scan_string_value(path, getattr(node, "lineno", 0), node.value)
            )
        elif isinstance(node, (ast.BinOp, ast.JoinedStr)):
            folded = _folded_string(node)
            if folded is not None:
                findings.extend(
                    _scan_string_value(path, getattr(node, "lineno", 0), folded)
                )
    return findings


def _folded_string(node: ast.AST) -> str | None:
    """Constant-fold a `+` chain of string literals, or return None.

    `"executive" + "-circle"` is one expression away from a literal and produced
    zero findings until this existed. A reviewer demonstrated the bypass against
    the gate modules this check now certifies as core, which is the one place a
    silent pass is most expensive.

    An f-string whose parts are all constant is the same trick with different
    syntax -- `f"{'executive'}{'-circle'}"` survived the first repair -- so
    `JoinedStr` and a constant `FormattedValue` fold too. Only literal operands
    fold. A branch assembled from runtime values remains outside this tripwire's
    proof boundary, and the report says so.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _folded_string(node.left)
        right = _folded_string(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            folded = _folded_string(value)
            if folded is None:
                return None
            parts.append(folded)
        return "".join(parts)
    if isinstance(node, ast.FormattedValue):
        # A format spec or conversion changes the rendered text, so only a bare
        # substitution of a constant is statically known.
        if node.conversion not in (-1, None) or node.format_spec is not None:
            return None
        return _folded_string(node.value)
    return None


def _scan_string_value(path: str, line: int, value: str) -> list[Finding]:
    """Scan one string value, wherever it came from."""
    findings: list[Finding] = []
    for name in PROVIDER_NAME_TOKENS:
        if _token_pattern(name).search(value):
            findings.append(Finding(path, line, "provider-name", name, _excerpt(value)))
    for kind in PROVIDER_KIND_TOKENS:
        if _token_pattern(kind).search(value):
            findings.append(
                Finding(path, line, "provider-kind-conditional", kind, _excerpt(value))
            )
    if PROVIDER_KIND_IDENTIFIER in value:
        findings.append(
            Finding(
                path, line, "provider-kind-conditional", PROVIDER_KIND_IDENTIFIER,
                _excerpt(value),
            )
        )
    if value in LEGACY_TYPE_LITERALS:
        findings.append(
            Finding(path, line, "provider-kind-conditional", value, _excerpt(value))
        )
    for match in _URL_RE.finditer(value):
        findings.append(Finding(path, line, "upstream-url", match.group(0), _excerpt(value)))
    for match in _DOMAIN_RE.finditer(value):
        findings.append(
            Finding(path, line, "provider-host-literal", match.group(0), _excerpt(value))
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
    return _deduplicate([*_scan_text_tokens(path, source), *_scan_ast(path, source)])


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
    """One legacy module measured against its recorded fingerprint baseline."""

    path: str
    baseline: dict[str, int]
    observed: dict[str, int]

    @property
    def new_fingerprints(self) -> dict[str, int]:
        """Findings that exceed, or do not appear in, the baseline."""
        return {
            fingerprint: count - self.baseline.get(fingerprint, 0)
            for fingerprint, count in self.observed.items()
            if count > self.baseline.get(fingerprint, 0)
        }

    @property
    def removed_fingerprints(self) -> dict[str, int]:
        return {
            fingerprint: count - self.observed.get(fingerprint, 0)
            for fingerprint, count in self.baseline.items()
            if count > self.observed.get(fingerprint, 0)
        }

    @property
    def regressed(self) -> bool:
        return bool(self.new_fingerprints)

    @property
    def improved(self) -> bool:
        return bool(self.removed_fingerprints)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "baseline_total": sum(self.baseline.values()),
            "observed_total": sum(self.observed.values()),
            "new_fingerprints": dict(sorted(self.new_fingerprints.items())),
            "removed_fingerprints": dict(sorted(self.removed_fingerprints.items())),
            "state": "regressed" if self.regressed else ("improved" if self.improved else "held"),
        }


def fingerprint_counts(findings: Sequence[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.fingerprint] = counts.get(finding.fingerprint, 0) + 1
    return dict(sorted(counts.items()))


def load_baseline(repo_root: Path) -> dict[str, dict[str, int]]:
    """Read the committed legacy baseline.

    Raises:
        FileNotFoundError: when it is missing. A gate whose baseline can vanish
            is a gate that can be switched off by deleting a file.
    """
    path = repo_root / BASELINE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"provider-neutrality baseline is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != BASELINE_SCHEMA:
        raise ValueError(f"unexpected baseline schema in {path}: {payload.get('schema')}")
    return {str(key): dict(value) for key, value in payload["modules"].items()}


def measure_legacy(repo_root: Path) -> dict[str, dict[str, int]]:
    """Measure every legacy module that currently carries provider knowledge."""
    measured: dict[str, dict[str, int]] = {}
    core = set(CORE_MODULES)
    for root in LEGACY_ROOTS:
        for path in sorted((repo_root / root).rglob("*.py")):
            relative = str(path.relative_to(repo_root))
            if relative in core:
                continue
            if any(
                relative == adapter_root or relative.startswith(f"{adapter_root}/")
                for adapter_root in PROVIDER_ADAPTER_ROOTS
            ):
                continue
            counts = fingerprint_counts(
                scan_source(relative, path.read_text(encoding="utf-8"))
            )
            if counts:
                measured[relative] = counts
    return measured


def scan_legacy(
    repo_root: Path, baselines: dict[str, dict[str, int]] | None = None
) -> list[LegacyStatus]:
    """Compare the legacy provider-aware modules against their baseline.

    These modules are *expected* to contain provider knowledge: they are the
    pre-ADR-0011 path. What is not expected is for them to gain any, and the
    comparison is per finding identity so removing an old leak can never buy
    room for a new one.
    """
    baseline = baselines if baselines is not None else load_baseline(repo_root)
    observed = measure_legacy(repo_root)
    statuses: list[LegacyStatus] = []
    for relative in sorted(set(baseline) | set(observed)):
        statuses.append(
            LegacyStatus(
                path=relative,
                baseline=dict(baseline.get(relative, {})),
                observed=dict(observed.get(relative, {})),
            )
        )
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
            "no legacy module gained a finding identity it did not already have. "
            "It is not a claim about every module in the repository."
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
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite the legacy fingerprint baseline from the current tree",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else _default_repo_root()

    if args.update_baseline:
        payload = {
            "schema": BASELINE_SCHEMA,
            "bead_id": BEAD_ID,
            "note": (
                "Legacy provider-aware modules: the pre-ADR-0011 resolution path "
                "that slice 6 (CL-mvet) replaces. Compared per finding identity, "
                "so removing an old leak never buys room for a new one. Regenerate "
                "with: uv run python scripts/checks/provider_neutrality.py "
                "--update-baseline"
            ),
            "modules": measure_legacy(repo_root),
        }
        (repo_root / BASELINE_PATH).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        print(f"wrote {BASELINE_PATH} for {len(payload['modules'])} legacy module(s)")
        return 0

    try:
        findings = scan_repository(repo_root)
        legacy = scan_legacy(repo_root)
    except (FileNotFoundError, ValueError) as exc:
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
            for fingerprint, extra in sorted(status.new_fingerprints.items()):
                print(f"  {status.path}: +{extra} {fingerprint}")
        print(
            "\nThese modules are the pre-ADR-0011 path and are being replaced, not "
            "extended. Add new provider knowledge to an adapter instead. Removing "
            "an unrelated old finding does not buy room for a new one."
        )
    if findings or regressions:
        return 1

    print(f"PASS: no provider knowledge in {len(CORE_MODULES)} core module(s)")
    for relative in CORE_MODULES:
        print(f"  {relative}")
    improved = [status for status in legacy if status.improved]
    print(
        f"Legacy provider-aware modules held at their baseline: "
        f"{sum(1 for status in legacy if status.observed)}"
    )
    for status in improved:
        print(
            f"  {status.path}: improved — rerun with --update-baseline to record it"
        )
    print(
        "This pass covers the modules named above. It is not a claim about every "
        "module in the repository."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
