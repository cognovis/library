"""Deterministic risk markers over foreign content (ADR-0011, `CL-lt51`).

**This is risk reduction, not detection, and the distinction is load-bearing.**
A marker says "a human reading this line would want to know it is here". It does
not say the content is hostile, and the absence of markers does not say it is
safe: an injection can be written in plain prose with no shell, no URL, and no
unusual byte. A clean scan therefore never skips the reviewer and never skips the
human gate -- see `update_admission.recommendation_for`, where that rule is
enforced rather than asserted.

Three properties make the scan usable as *recorded evidence* rather than as an
opinion:

- **Pure function of bytes.** No network, no model, no clock, no filesystem, no
  environment. Two machines that hold the same content produce the same report.
- **Ordered.** Markers sort by path, then line, then class, then rule, so a
  packet's scan section is byte-stable and a diff between two scans is readable.
- **Bounded.** Every excerpt is truncated. The report is read by a human in a
  decision packet, and an unbounded excerpt turns the packet into the content it
  was supposed to summarize.

The rule table is deliberately blunt and deliberately noisy. A rule that tries to
be precise about whether `curl` is dangerous has to model intent, and a scanner
that models intent is the "clean scan means safe" claim this module refuses to
make.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .executable_admission import content_digest, validated_digest

#: The recorded form of one scan.
SCAN_SCHEMA = "cognovis.marketplace-update-scan.v1"

#: The closed vocabulary. A new marker class is a deliberate addition here, never
#: an ad-hoc string at a call site -- the packet renders counts per class, and an
#: invented class would appear as a category nobody defined.
MARKER_CLASSES = (
    "shell-invocation",
    "network-destination",
    "credential-path",
    "filesystem-escape",
    "encoding-anomaly",
    "instruction-override",
)

#: How much of a matched line a marker carries. Long enough to recognize the
#: line, short enough that a packet stays a summary.
EXCERPT_LIMIT = 200

#: Characters that are present in the bytes and absent from the rendering: zero
#: width members, bidirectional overrides, and the byte-order mark in the middle
#: of a document. Their whole purpose is that a reviewer does not see them.
_INVISIBLE = re.compile(
    "[​‌‍⁠﻿‪‫‬‭‮⁦⁧⁨⁩]"
)

#: A long unbroken run of base64/hex-shaped characters. Content a model follows
#: is prose; an encoded blob inside it is at minimum something a reviewer should
#: be shown decoded.
_ENCODED_BLOB = re.compile(r"[A-Za-z0-9+/=_-]{120,}")

#: `(marker_class, rule, pattern)`. Rules are named because a packet that says
#: "shell-invocation" and nothing else cannot be argued with; one that says
#: `piped-download-to-shell` can be.
_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "shell-invocation",
        "piped-download-to-shell",
        re.compile(r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|d)?sh\b", re.IGNORECASE),
    ),
    (
        "shell-invocation",
        "shell-command-string",
        re.compile(r"\b(?:ba|z|d)?sh\b\s+-c\b|\bos\.system\s*\(|\bsubprocess\b|\bchild_process\b"),
    ),
    ("shell-invocation", "eval", re.compile(r"\beval\s*\(|\beval\s+[\"'$]")),
    ("shell-invocation", "recursive-delete", re.compile(r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*\b")),
    ("shell-invocation", "privilege-escalation", re.compile(r"(?:^|\s)sudo\s+\S")),
    ("shell-invocation", "make-executable", re.compile(r"\bchmod\s+[+0-7][^\n]*x")),
    (
        "shell-invocation",
        "command-substitution",
        re.compile(r"\$\([^)\n]+\)|`[^`\n]+`"),
    ),
    (
        "network-destination",
        "url",
        re.compile(r"\bhttps?://[^\s\"'>)\]]+", re.IGNORECASE),
    ),
    (
        "network-destination",
        "ip-address",
        re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])"),
    ),
    (
        "network-destination",
        "transfer-tool",
        re.compile(r"(?:^|\s)(?:curl|wget|nc|netcat|scp|rsync|ssh)\s+\S", re.IGNORECASE),
    ),
    (
        "credential-path",
        "private-key-or-ssh",
        re.compile(r"~?/?\.ssh/|\bid_(?:rsa|ed25519|ecdsa)\b|BEGIN [A-Z ]*PRIVATE KEY"),
    ),
    (
        "credential-path",
        "credential-file",
        re.compile(r"(?:^|[\s\"'/])\.(?:env|netrc|npmrc|pypirc)\b|\.aws/credentials|\.config/gh"),
    ),
    (
        "credential-path",
        "secret-environment-variable",
        re.compile(
            r"\b[A-Z][A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIALS)\b"
            r"|\bAuthorization\s*:\s*Bearer\b",
        ),
    ),
    ("credential-path", "keychain", re.compile(r"\bsecurity\s+find-\w*-password\b|\bkeychain\b", re.IGNORECASE)),
    (
        "filesystem-escape",
        "parent-traversal",
        re.compile(r"\.\./\.\.|(?:^|[\s\"'(])\.\./"),
    ),
    (
        "filesystem-escape",
        "system-path",
        re.compile(r"(?<![\w.])/(?:etc|usr|bin|sbin|var|private|System|Library)/"),
    ),
    (
        "filesystem-escape",
        "home-escape",
        re.compile(r"~/(?!\.agents/|\.claude/skills/)[.\w-]+"),
    ),
    (
        "instruction-override",
        "override-prior-instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b[^\n]{0,40}\b"
            r"(?:previous|prior|earlier|above|all)\b[^\n]{0,40}\b(?:instruction|rule|prompt)",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction-override",
        "conceal-from-user",
        re.compile(
            r"\b(?:do not|don't|never)\b[^\n]{0,30}\b(?:tell|inform|show|mention|reveal)\b"
            r"[^\n]{0,20}\b(?:the )?(?:user|human|operator)\b"
            r"|\bwithout\b[^\n]{0,20}\b(?:telling|informing|asking)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction-override",
        "identity-reassignment",
        re.compile(
            r"\byou are (?:now|actually)\b|\bnew system prompt\b|\bsystem\s*:\s*you\b",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction-override",
        "exfiltration-request",
        re.compile(
            r"\b(?:send|post|upload|transmit|report)\b[^\n]{0,40}\b"
            r"(?:key|token|secret|credential|password|contents of)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class RiskMarker:
    """One thing in the bytes a reviewer would want to have been shown."""

    marker_class: str
    rule: str
    path: str
    line: int
    excerpt: str

    def __post_init__(self) -> None:
        if self.marker_class not in MARKER_CLASSES:
            raise ValueError(
                f"unknown risk-marker class {self.marker_class!r}; the vocabulary is "
                f"{list(MARKER_CLASSES)}"
            )
        if not isinstance(self.rule, str) or not self.rule.strip():
            raise ValueError("a risk marker names the rule that produced it")
        if self.line < 0:
            raise ValueError("a risk marker's line is 1-based, or 0 for whole-file findings")

    def sort_key(self) -> tuple[str, int, str, str]:
        return (self.path, self.line, self.marker_class, self.rule)

    def to_dict(self) -> dict[str, Any]:
        return {
            "marker_class": self.marker_class,
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "excerpt": self.excerpt,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RiskMarker":
        return cls(
            marker_class=str(data["marker_class"]),
            rule=str(data["rule"]),
            path=str(data["path"]),
            line=int(data["line"]),
            excerpt=str(data["excerpt"]),
        )


@dataclass(frozen=True)
class ScanReport:
    """Every marker found in one content set, bound to the bytes it read.

    `content_digest` is not decoration. A report that lists its findings and not
    its subject cannot be checked against anything: two revisions of an item can
    produce identical findings -- adding a comment line changes no marker -- and
    a packet that bound only to the findings would accept a scan of the previous
    revision as a scan of this one. The digest is the same function the admission
    ledger binds decisions with, adopted rather than forked, so "the bytes the
    scan read" and "the bytes the operator admitted" are comparable values.
    """

    markers: tuple[RiskMarker, ...]
    scanned_paths: tuple[str, ...]
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "markers", tuple(self.markers))
        object.__setattr__(self, "scanned_paths", tuple(self.scanned_paths))
        validated_digest(self.content_digest)

    def counts(self) -> dict[str, int]:
        """Marker count per class, for the packet's summary line."""
        counts: dict[str, int] = {}
        for marker in self.markers:
            counts[marker.marker_class] = counts.get(marker.marker_class, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCAN_SCHEMA,
            "content_digest": self.content_digest,
            "markers": [marker.to_dict() for marker in self.markers],
            "scanned_paths": list(self.scanned_paths),
            "counts": self.counts(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScanReport":
        if data.get("schema") != SCAN_SCHEMA:
            raise ValueError(
                f"unexpected scan schema {data.get('schema')!r}; expected {SCAN_SCHEMA}"
            )
        return cls(
            markers=tuple(RiskMarker.from_dict(entry) for entry in data["markers"]),
            scanned_paths=tuple(str(path) for path in data["scanned_paths"]),
            content_digest=str(data["content_digest"]),
        )

    def digest(self) -> str:
        """A content digest of this report, so a packet can bind to its scan."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _excerpt(text: str) -> str:
    """One line, whitespace-normalized and truncated.

    Normalized because a marker is read in a table, and a line carrying its own
    newlines or a hundred spaces of indentation breaks the table rather than the
    reader's attention.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= EXCERPT_LIMIT:
        return collapsed
    return collapsed[: EXCERPT_LIMIT - 1] + "…"


def _scan_text(path: str, text: str) -> list[RiskMarker]:
    markers: list[RiskMarker] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for marker_class, rule, pattern in _RULES:
            if pattern.search(line):
                markers.append(
                    RiskMarker(
                        marker_class=marker_class,
                        rule=rule,
                        path=path,
                        line=number,
                        excerpt=_excerpt(line),
                    )
                )
        if _INVISIBLE.search(line):
            markers.append(
                RiskMarker(
                    marker_class="encoding-anomaly",
                    rule="invisible-characters",
                    path=path,
                    line=number,
                    # The excerpt shows the codepoints rather than the characters,
                    # because rendering them is exactly how they hide.
                    excerpt=_excerpt(
                        "invisible codepoints present: "
                        + " ".join(
                            sorted({f"U+{ord(char):04X}" for char in _INVISIBLE.findall(line)})
                        )
                    ),
                )
            )
        if _ENCODED_BLOB.search(line):
            markers.append(
                RiskMarker(
                    marker_class="encoding-anomaly",
                    rule="encoded-blob",
                    path=path,
                    line=number,
                    excerpt=_excerpt(line),
                )
            )
    return markers


def scan_content(files: Mapping[str, bytes]) -> ScanReport:
    """Scan one item's complete content.

    Args:
        files: Item-relative path to bytes. The complete item, not a diff: a line
            that is only dangerous next to a line it did not change with is
            invisible to a diff-only scan.

    Returns:
        The report, with markers in a stable order.
    """
    markers: list[RiskMarker] = []
    for path in sorted(files):
        content = files[path]
        try:
            text = bytes(content).decode("utf-8")
        except UnicodeDecodeError:
            # Not text, so no rule applies -- and that is itself the finding.
            # Content a model follows is text; a binary member inside it is
            # something a reviewer has to look at with different tools.
            markers.append(
                RiskMarker(
                    marker_class="encoding-anomaly",
                    rule="non-text-content",
                    path=path,
                    line=0,
                    excerpt=f"{len(content)} bytes that are not valid UTF-8 text",
                )
            )
            continue
        markers.extend(_scan_text(path, text))
    return ScanReport(
        markers=tuple(sorted(markers, key=lambda marker: marker.sort_key())),
        scanned_paths=tuple(sorted(files)),
        content_digest=content_digest(files),
    )


def scan_items(contents: Mapping[str, Mapping[str, bytes]]) -> dict[str, ScanReport]:
    """Scan several items, keyed by qualified identity."""
    return {identity: scan_content(files) for identity, files in sorted(contents.items())}


def merged_counts(reports: Sequence[ScanReport]) -> dict[str, int]:
    """Marker counts across several items, for a change-set-wide summary."""
    total: dict[str, int] = {}
    for report in reports:
        for marker_class, count in report.counts().items():
            total[marker_class] = total.get(marker_class, 0) + count
    return total


__all__ = [
    "EXCERPT_LIMIT",
    "MARKER_CLASSES",
    "SCAN_SCHEMA",
    "RiskMarker",
    "ScanReport",
    "merged_counts",
    "scan_content",
    "scan_items",
]
