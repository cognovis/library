"""Catalog-derived routing: which installed capability answers a request.

This is the engine behind the platform-owned navigator placement ADR-0011 calls
`ask-malte`, and the constraint on it is stronger than a recommendation:

- It MUST resolve candidates through **catalog data** — the entries under
  `library.*` and the registered sources under `sources.catalogs` and
  `sources.marketplaces` — and through **canonical context pointers** such as
  `~/.agents/AGENTS.md`, `docs/PRIMITIVES.md`, and the installed workspace set.
- It MUST NOT hard-code provider names, sibling-repository paths, or a routing
  table of repositories. A routing answer that names a catalog must have read
  that name out of the catalog in that same run.

The consequence is deliberate: on a machine with fewer catalogs registered this
returns a correct, narrower answer instead of a confidently wrong one naming a
repository that is not there. That failure mode is not hypothetical — a routing
table baked into a navigator is right until someone's machine differs from the
author's, and then it is authoritative and wrong, which is worse than silent.

The rule is enforced, not documented: `RoutingAnswer.assert_catalog_derived`
re-reads the rendered answer and refuses any source-shaped token that is not in
the set of names this run actually read. A regression fails a test rather than
reaching a user as a plausible sentence.

This module names no provider, no provider kind, and no upstream URL; it is
scanned as a core module by `scripts/checks/provider_neutrality.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .catalog import get_catalogs, get_entries, get_marketplaces, normalize_catalog_identity
from .primitives import all_primitive_names

#: Primitives a routing answer may propose. Routing answers "what should I use",
#: and these are the artifacts a person or agent uses directly.
ROUTABLE_PRIMITIVES = ("skill", "agent", "workspace", "prompt", "standard")

#: Canonical context pointers. They are *paths to read*, never a source of
#: authority about which repository holds what: a pointer that does not exist on
#: this machine is reported absent and contributes nothing.
DEFAULT_CONTEXT_POINTERS: tuple[tuple[str, str], ...] = (
    ("agent-rules", "~/.agents/AGENTS.md"),
    ("primitive-reference", "docs/PRIMITIVES.md"),
    ("repository-navigation", "AGENTS.md"),
)

#: Tokens that look like a source: a URL, or a dotted host-shaped word. Used only
#: to police this module's own output against what it read.
_SOURCE_TOKEN_RE = re.compile(
    r"(?:https?://[^\s'\"`)]+)|(?:git@[\w.-]+:[\w./-]+)", re.IGNORECASE
)

_WORD_RE = re.compile(r"[a-z0-9]+")

#: The closed set of notes this module can produce. A prefix check was tried
#: first and review walked straight through it: a note reading
#: "no source is registered on this machine; try sussdorff-core" starts with an
#: allowed prefix and still names an unread repository. `startswith` proves the
#: opening words, and the claim being made is about the whole sentence.
NOTE_NO_CONTEXT_POINTERS = "absent-context-pointers"
NOTE_NO_REGISTERED_SOURCE = "no-registered-source"
NOTE_KINDS = (NOTE_NO_CONTEXT_POINTERS, NOTE_NO_REGISTERED_SOURCE)


class RoutingNotCatalogDerived(RuntimeError):
    """A routing answer named a source this run did not read.

    The whole value of catalog-derived routing is that its answer is true on the
    machine it ran on. A name that did not come from the catalog is a claim about
    somebody else's machine.
    """


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(str(text).lower()))


@dataclass(frozen=True)
class RoutingNote:
    """One note this module produced, identified by kind rather than by wording.

    A note is a typed value, not free text, because the guarantee is about
    provenance: the run can attest to what it read, and it cannot attest to a
    sentence a caller wrote. Rendering happens here, from the kind and its own
    data, so there is no text a caller can supply at all.
    """

    kind: str
    detail: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in NOTE_KINDS:
            raise ValueError(f"unknown routing note kind: {self.kind!r}")
        object.__setattr__(self, "detail", tuple(str(item) for item in self.detail))

    def render(self) -> str:
        if self.kind == NOTE_NO_CONTEXT_POINTERS:
            return (
                "context pointers not present on this machine, so they contributed "
                f"nothing: {sorted(self.detail)}"
            )
        return (
            "no source is registered on this machine, so no candidate can be "
            "attributed to one"
        )


@dataclass(frozen=True)
class ContextPointer:
    """One canonical context file, and whether it exists on this machine."""

    label: str
    path: Path
    present: bool

    def describe(self) -> str:
        state = "read" if self.present else "absent"
        return f"{self.label} ({state}): {self.path}"


@dataclass(frozen=True)
class RoutingCandidate:
    """One catalog entry proposed as an answer, with why it was proposed."""

    primitive: str
    name: str
    catalog_name: str
    catalog_identity: str
    summary: str
    score: int
    matched_terms: tuple[str, ...]

    def describe(self) -> str:
        terms = ", ".join(self.matched_terms) or "name match"
        source = self.catalog_name or "unattributed catalog entry"
        return f"{self.primitive}:{self.name} from {source} (matched: {terms})"


@dataclass(frozen=True)
class RoutingAnswer:
    """A routing answer plus the exact evidence this run read to produce it."""

    query: str
    candidates: tuple[RoutingCandidate, ...]
    catalogs_read: tuple[str, ...]
    identities_read: tuple[str, ...]
    context_pointers: tuple[ContextPointer, ...]
    unmatched: bool = False
    notes: tuple[RoutingNote, ...] = field(default_factory=tuple)

    def named_sources(self) -> tuple[str, ...]:
        """Every catalog name and identity this answer mentions."""
        names = {candidate.catalog_name for candidate in self.candidates}
        names |= {candidate.catalog_identity for candidate in self.candidates}
        return tuple(sorted(name for name in names if name))

    def render(self) -> str:
        """The answer as text, including what it read and what it did not find."""
        lines = [f"Request: {self.query}"]
        if self.candidates:
            lines.append("Candidates:")
            lines.extend(f"  - {candidate.describe()}" for candidate in self.candidates)
        else:
            lines.append(
                "No catalog entry matched. This machine's registered catalogs are "
                "the whole of what was searched; nothing outside them is proposed."
            )
        lines.append(
            "Catalogs read this run: "
            + (", ".join(self.catalogs_read) or "none registered")
        )
        lines.append("Context pointers:")
        lines.extend(f"  - {pointer.describe()}" for pointer in self.context_pointers)
        lines.extend(f"Note: {note.render()}" for note in self.notes)
        return "\n".join(lines)

    def assert_catalog_derived(self) -> "RoutingAnswer":
        """Refuse an answer naming a source this run did not read.

        Checked on the rendered text, not on the structured fields, because the
        rendered text is what a reader acts on. A structured check would pass an
        answer whose prose named a repository nobody registered.

        Prose is checked by **provenance, not by pattern**. A URL scan cannot
        recognize a bare repository name — review put `sussdorff-core` into a
        note and the scan passed it, since a plain sibling name is the most
        likely way a routing table would leak. A prefix check was the next
        attempt and review walked through that too, by appending the sibling
        name to an allowed opening. So a note is not text at all: it is a typed
        value whose wording this module renders, and there is no field for a
        caller's sentence to arrive in.
        """
        read = {name for name in (*self.catalogs_read, *self.identities_read) if name}
        for note in self.notes:
            if not isinstance(note, RoutingNote):
                raise RoutingNotCatalogDerived(
                    f"routing answer carries a note that is not a typed RoutingNote: "
                    f"{note!r}. Free prose cannot be attributed to what the run read, "
                    "and a bare repository name in it would read as fact"
                )
        rendered = self.render()
        for match in _SOURCE_TOKEN_RE.finditer(rendered):
            token = match.group(0).rstrip(".,);")
            if token not in read and normalize_catalog_identity(token) not in read:
                raise RoutingNotCatalogDerived(
                    f"routing answer names {token!r}, which this run did not read "
                    "from the catalog; a routing answer describes the machine it ran on"
                )
        for name in self.named_sources():
            if name not in read:
                raise RoutingNotCatalogDerived(
                    f"routing answer attributes a candidate to {name!r}, which is not "
                    "among the catalogs this run read"
                )
        return self


def _entry_catalog(entry: Mapping[str, Any]) -> tuple[str, str]:
    library = (entry.get("metadata") or {}).get("library") or {}
    return (
        str(library.get("source_catalog") or ""),
        str(library.get("catalog_identity") or ""),
    )


def _registered_sources(catalog: Mapping[str, Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Registered source names mapped to their canonical identity.

    Both `sources.catalogs` and `sources.marketplaces` are read: a routing answer
    that only knew about catalogs would be unable to say where an entry came from
    on a machine whose content is registered as a marketplace.
    """
    identities: dict[str, str] = {}
    for source in (*get_catalogs(dict(catalog)), *get_marketplaces(dict(catalog))):
        if not isinstance(source, Mapping):
            continue
        name = str(source.get("name") or source.get("id") or "").strip()
        if not name:
            continue
        raw = str(source.get("source") or source.get("clone_url") or "").strip()
        identities[name] = normalize_catalog_identity(raw) if raw else ""
    return identities, tuple(sorted(identities))


def _score(entry: Mapping[str, Any], terms: set[str]) -> tuple[int, tuple[str, ...]]:
    name_words = _words(entry.get("name") or "")
    description_words = _words(entry.get("description") or "")
    tag_words: set[str] = set()
    for tag in entry.get("tags") or ():
        tag_words |= _words(tag)

    matched: set[str] = set()
    score = 0
    for term in terms:
        if term in name_words:
            score += 5
            matched.add(term)
        elif term in tag_words:
            score += 3
            matched.add(term)
        elif term in description_words:
            score += 1
            matched.add(term)
    return score, tuple(sorted(matched))


def resolve_context_pointers(
    repo_root: Path | None = None,
    pointers: Sequence[tuple[str, str]] = DEFAULT_CONTEXT_POINTERS,
) -> tuple[ContextPointer, ...]:
    """Resolve the canonical context pointers against this machine.

    An absent pointer is reported, never substituted. "The file that would have
    told me is not here" and "I know the answer anyway" are different states, and
    collapsing them is how a navigator becomes confidently wrong.
    """
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    resolved: list[ContextPointer] = []
    for label, raw in pointers:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        resolved.append(ContextPointer(label=label, path=path, present=path.is_file()))
    return tuple(resolved)


def route(
    catalog: Mapping[str, Any],
    query: str,
    *,
    primitives: Iterable[str] = ROUTABLE_PRIMITIVES,
    repo_root: Path | None = None,
    context_pointers: Sequence[ContextPointer] | None = None,
    limit: int = 5,
) -> RoutingAnswer:
    """Route one request to catalog entries, naming only what this run read.

    Args:
        catalog: The loaded catalog document for this machine.
        query: The request in the caller's own words.
        primitives: Which primitive types may be proposed.
        repo_root: Root for relative context pointers.
        context_pointers: Pre-resolved pointers; resolved here when omitted.
        limit: Maximum candidates to propose.

    Returns:
        The answer, already checked against its own evidence.
    """
    terms = _words(query)
    known = set(all_primitive_names())
    identities, catalog_names = _registered_sources(catalog)
    pointers = (
        tuple(context_pointers)
        if context_pointers is not None
        else resolve_context_pointers(repo_root)
    )

    scored: list[RoutingCandidate] = []
    for primitive in primitives:
        if primitive not in known:
            continue
        for entry in get_entries(dict(catalog), primitive):
            if not isinstance(entry, Mapping):
                continue
            score, matched = _score(entry, terms)
            if score <= 0:
                continue
            source_name, source_identity = _entry_catalog(entry)
            scored.append(
                RoutingCandidate(
                    primitive=primitive,
                    name=str(entry.get("name") or ""),
                    catalog_name=source_name,
                    catalog_identity=source_identity or identities.get(source_name, ""),
                    summary=str(entry.get("description") or ""),
                    score=score,
                    matched_terms=matched,
                )
            )

    scored.sort(key=lambda candidate: (-candidate.score, candidate.primitive, candidate.name))
    selected = tuple(scored[: max(0, int(limit))])

    notes: list[RoutingNote] = []
    absent = [pointer.label for pointer in pointers if not pointer.present]
    if absent:
        notes.append(RoutingNote(kind=NOTE_NO_CONTEXT_POINTERS, detail=tuple(sorted(absent))))
    if not catalog_names:
        notes.append(RoutingNote(kind=NOTE_NO_REGISTERED_SOURCE))

    answer = RoutingAnswer(
        query=query,
        candidates=selected,
        catalogs_read=catalog_names,
        identities_read=tuple(sorted({value for value in identities.values() if value})),
        context_pointers=pointers,
        unmatched=not selected,
        notes=tuple(notes),
    )
    return answer.assert_catalog_derived()
