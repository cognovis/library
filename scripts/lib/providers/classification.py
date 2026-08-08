"""Library-owned classification of provider items.

Classification is a Library axis (A4), not a provider axis. Nothing here knows
which provider supplied an item; it works from an item's own path hint and,
where available, its content.

Two rules are recorded because they are decisions rather than derivations:

- `library_type` must be an existing primitive type. Introducing a type
  requires its own ADR (ADR-0011 schema table), so an unrecognized artifact is
  classified by extension and marked low-confidence rather than given a new type.
- `skill_class` is derived from the upstream frontmatter flag ADR-0011 names
  (`disable-model-invocation: true` marks a navigator). That flag lives in
  content. ADR-0011 admits exactly `navigator` and `procedure`, so a
  classification produced *without* content omits the key entirely and records
  why. Emitting a third state would invent vocabulary the ADR does not have;
  guessing `procedure` would silently misclassify every navigator. Absence of a
  key is the one honest option, and it is queryable through
  `skill_class_source`.
"""

from __future__ import annotations

import re
from typing import Mapping

#: Marker file basenames that identify a primitive directory, lowercased.
ITEM_MARKERS: Mapping[str, str] = {
    "skill.md": "skill",
    "agent.md": "agent",
    "standard.md": "standard",
    "workflow.md": "workflow",
}

#: Fallback classification by file extension when no marker file applies.
EXTENSION_DEFAULTS: Mapping[str, str] = {
    ".md": "prompt",
    ".py": "script",
    ".sh": "script",
    ".zsh": "script",
    ".bash": "script",
}

DEFAULT_LIBRARY_TYPE = "prompt"

#: ADR-0011 `Executable admission`: Workflow, Pi extension, Pi profile that
#: loads code, hook, or script. Everything else is inert and never inherits
#: executable trust by sharing a bundle, collection, or provider.
EXECUTABLE_TYPES = frozenset(
    {"workflow", "pi-extension", "pi-profile", "script", "hook", "guardrail"}
)

#: The complete ADR-0011 vocabulary. There is no third state.
SKILL_CLASSES = ("navigator", "procedure")

_FRONTMATTER_RE = re.compile(rb"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_NAVIGATOR_FLAG_RE = re.compile(
    rb"^\s*disable-model-invocation\s*:\s*(true|yes)\s*$", re.IGNORECASE | re.MULTILINE
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def library_type_for(hint: str | None) -> tuple[str, str]:
    """Classify one item from its path hint.

    Returns:
        `(library_type, basis)`, where basis records how the type was reached
        so a low-confidence classification stays visible downstream.
    """
    if not hint:
        return DEFAULT_LIBRARY_TYPE, "no-hint-default"
    basename = hint.rsplit("/", 1)[-1].lower()
    marker = ITEM_MARKERS.get(basename)
    if marker:
        return marker, "marker-file"
    suffix = basename[basename.rfind(".") :] if "." in basename else ""
    extension = EXTENSION_DEFAULTS.get(suffix)
    if extension:
        return extension, "extension-default"
    return DEFAULT_LIBRARY_TYPE, "unrecognized-default"


def skill_class_for(library_type: str, content: bytes | None) -> str | None:
    """Derive `skill_class` from upstream frontmatter.

    Returns:
        `navigator` or `procedure`, or `None` when the item is not a Skill or
        its content was not inspected. `None` means "not determined"; it is
        never rendered into the classification as a value.
    """
    if library_type != "skill" or content is None:
        return None
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None
    return "navigator" if _NAVIGATOR_FLAG_RE.search(match.group(1)) else "procedure"


def classification_for(
    library_type: str, basis: str, content: bytes | None
) -> dict[str, str]:
    """The Library-owned classification metadata for one item."""
    classification = {
        "type_basis": basis,
        "content_inspected": "yes" if content is not None else "no",
    }
    skill_class = skill_class_for(library_type, content)
    if skill_class is not None:
        classification["skill_class"] = skill_class
        classification["skill_class_source"] = "upstream-frontmatter"
    elif library_type == "skill":
        classification["skill_class_source"] = (
            "content-inspected-without-frontmatter"
            if content is not None
            else "not-determined-without-content"
        )
    return classification


def executable_admission_for(library_type: str) -> str:
    """`pending` for an executable type, `inert` otherwise.

    Slice 1 records the initial state only. The gate that moves an item from
    `pending` to `admitted` or `refused` is slice 2 (`CL-n7ex`).
    """
    return "pending" if library_type in EXECUTABLE_TYPES else "inert"


def library_name_for(upstream_name: str) -> str:
    """Project an upstream name onto a Library-scoped name.

    This is the recorded projection rule ADR-0011 requires before `library_name`
    may differ from `upstream_name`: lowercase, non-alphanumeric runs collapse
    to a single hyphen, leading and trailing hyphens are stripped. The upstream
    name itself is never modified.
    """
    slug = _SLUG_RE.sub("-", upstream_name.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"upstream name has no projectable Library name: {upstream_name!r}")
    return slug
