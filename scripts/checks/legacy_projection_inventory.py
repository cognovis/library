#!/usr/bin/env python3
"""Derive the ADR-0011 legacy projection inventory from the machine (CL-m6cc AC5).

ADR-0011 `Legacy Projection Disposition` published a survey taken by **matching
names** against an upstream repository, and then concluded that no listed
projection is currently non-compliant. The `CL-2p73` review pointed out that the
conclusion does not follow from the method: the same paragraph states that with
zero receipts nothing local can say whether a directory came from an upstream
provider, from a first-party catalog, or from a hand copy.

This generator replaces that survey. It reads bytes, computes a normalized
content digest per projection, and attributes provenance **only** by matching
that digest against digests a provider actually served. A projection whose
digest matches nothing is recorded `rights-unresolved-pending-digest-attribution`
-- not compliant, not condemned, and blocked from re-materialization until the
digest resolves.

The digest index is data, not code: pass `--digest-index` with a JSON mapping of
`normalized content digest -> [provider identity, upstream id]` produced by an
actual retrieval. Without one, every projection is unattributed, which is the
honest present state of a machine whose providers have never been fetched
through the ADR-0011 cache.

Usage:
    uv run python scripts/checks/legacy_projection_inventory.py
    uv run python scripts/checks/legacy_projection_inventory.py \\
        --root ~/.claude/skills --root ~/.claude/workflows \\
        --digest-index resolved-digests.json \\
        --receipts ~/.config/library/global.lock.foreign-receipts.json

The generator is read-only with respect to the projections it inventories. It
writes only its two output artifacts.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.inventory import Rights  # noqa: E402
from lib.providers.legacy_projections import (  # noqa: E402
    INVENTORY_SCHEMA,
    PENDING_DIGEST_ATTRIBUTION,
    DeclaredProvenance,
    NonComplianceRegister,
    classify_inventory,
    inventory_document,
    receipt_index_for,
    scan_projections,
)
from lib.providers.receipts import ReceiptStore  # noqa: E402
from lib.providers.reference_rights import rights_for  # noqa: E402

#: Catalogs whose content is the operator's own. A first-party catalog's
#: redistribution question is answered by the fact that the operator authored and
#: publishes it, and the evidence is the catalog identity recorded in the lock
#: receipt itself. This list lives in the generator, not in the core modules: it
#: names specific catalogs, which is exactly what a neutral module may not do.
FIRST_PARTY_CATALOGS: tuple[str, ...] = (
    "https://github.com/cognovis/library",
    "https://github.com/cognovis/library-core",
    "https://github.com/sussdorff/library-core",
)

#: The two roots ADR-0011 inventories. They are the operator's real harness
#: paths, and they are defaults rather than constants so the generator is
#: testable against a fixture tree.
DEFAULT_ROOTS: tuple[Path, ...] = (
    Path.home() / ".claude" / "skills",
    Path.home() / ".claude" / "workflows",
)

DEFAULT_RECEIPT_STORES: tuple[Path, ...] = (
    Path.home() / ".config" / "library" / "global.lock.foreign-receipts.json",
)

#: Existing v1/v2 locks whose receipts declare provenance for a projected path.
DEFAULT_LOCKS: tuple[Path, ...] = (
    Path.home() / ".config" / "library" / "global.lock",
)

#: Where the production non-compliance register lives. It is the same location
#: `ForeignState.for_locks` derives, so arming it here is arming the register
#: every production writer consults -- not a second, parallel one.
DEFAULT_REGISTER = (
    Path(
        os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    )
    / "library"
    / "foreign"
    / "non-compliant-projections.json"
)

JSON_ARTIFACT = REPO_ROOT / "docs" / "reports" / "legacy-projection-inventory.json"
MARKDOWN_ARTIFACT = REPO_ROOT / "docs" / "reports" / "legacy-projection-inventory.md"


def load_digest_index(path: Path | None) -> dict[str, tuple[str, str]]:
    """Read a digest-to-upstream mapping produced by an actual retrieval.

    Raises:
        ValueError: for a malformed mapping. A damaged index read as empty would
            quietly mark attributed content unattributed, which is safe, and a
            damaged index read permissively would do the opposite -- so the
            index refuses rather than guessing in either direction.
    """
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("a digest index maps a content digest to its upstream identity")
    index: dict[str, tuple[str, str]] = {}
    for digest, identity in payload.items():
        if not isinstance(identity, (list, tuple)) or len(identity) != 2:
            raise ValueError(
                f"digest {digest!r} must map to [provider_identity, upstream_id]"
            )
        index[str(digest)] = (str(identity[0]), str(identity[1]))
    return index


def _first_party_rights(catalog_identity: str) -> Rights:
    return Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source=(
            f"first-party catalog {catalog_identity}, recorded as the "
            "catalog_identity of this projection's own lock receipt"
        ),
    )


def _rights_for(provider_identity: str) -> Rights | None:
    """Recorded rights for one provider or catalog identity, or `None`.

    `None` is the honest answer for an identity nobody recorded rights for, and
    it resolves the projection to `unknown`. Having installed something once is
    not a grant.
    """
    reference = rights_for(provider_identity)
    if reference is not None:
        return reference
    if provider_identity in FIRST_PARTY_CATALOGS:
        return _first_party_rights(provider_identity)
    return None


def _normalized(path_value: str) -> str:
    return str(Path(str(path_value).strip().rstrip("/")))


def declared_provenance_from_lock(
    lock_path: Path,
) -> dict[str, DeclaredProvenance]:
    """Every projected path an existing lock receipt claims, with its catalog.

    The operator's real `global.lock` is v1-shaped: it records an
    `install_target` and a list of `bridge_symlinks` rather than a `targets`
    inventory. Both sides are indexed, because a harness bridge under
    `~/.claude/skills` is the path this inventory scans while the canonical
    target lives elsewhere -- and treating the bridge as unclaimed would report
    the Library's own installs as unknown-origin.
    """
    path = Path(lock_path)
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment dependent
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = payload.get("installed") or []
    if not isinstance(entries, list):
        raise ValueError(
            f"{path} has a malformed `installed` list; a damaged lock is never "
            "read as an empty one"
        )
    declared: dict[str, DeclaredProvenance] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        # Every field below is required, and none of them substitutes for
        # another. Review supplied an entry carrying only `source` and the
        # generator turned it into `receipt-declared` provenance with `granted`
        # first-party rights: `catalog_identity` was allowed to fall back to
        # `source`, and `source_commit` was never checked at all. A declaration
        # that cannot be reconstructed is not weak evidence, it is the absence
        # of evidence with a URL attached.
        catalog = str(entry.get("catalog_identity") or "").strip()
        name = str(entry.get("name") or "").strip()
        commit = str(entry.get("source_commit") or "").strip()
        source = str(entry.get("source") or "").strip()
        # `source` is required and is never replaced by the entry's name. The
        # fallback `entry.get("source") or name` made a name into an upstream
        # identity, which is precisely the evidence this module refuses
        # everywhere else.
        if not catalog or not name or not commit or not source:
            continue
        receipt_id = f"{entry.get('type')}:{name}:{entry.get('scope')}"
        provenance = DeclaredProvenance(
            receipt_id=receipt_id,
            provider_identity=catalog,
            upstream_id=source,
            evidence_source=(
                f"lock receipt {receipt_id} in {path} records catalog_identity "
                f"{catalog} and source_commit {commit}"
            ),
        )
        claimed = [entry.get("install_target")]
        for bridge in entry.get("bridge_symlinks") or []:
            claimed.append(str(bridge).split("->")[0])
        for claim in claimed:
            if claim:
                declared[_normalized(str(claim))] = provenance
    return declared


def build_document(
    *,
    roots: Sequence[Path],
    digest_index: Mapping[str, tuple[str, str]],
    receipt_store_paths: Sequence[Path],
    lock_paths: Sequence[Path] = (),
    observed_at: str,
) -> dict[str, Any]:
    """The whole inventory, derived: digests, rights, receipts, disposition."""
    stores = [ReceiptStore(path) for path in receipt_store_paths if Path(path).is_file()]
    declared: dict[str, DeclaredProvenance] = {}
    read_locks: list[str] = []
    for lock_path in lock_paths:
        found = declared_provenance_from_lock(Path(lock_path))
        if found:
            read_locks.append(str(lock_path))
        declared.update(found)

    receipt_index = dict(receipt_index_for(stores))
    # A v1 lock receipt claiming a path is still a receipt. Reporting it as
    # unreceipted would mean the Library's own installs read as unreproducible.
    for claimed, provenance in declared.items():
        receipt_index.setdefault(claimed, provenance.receipt_id)

    classifications = classify_inventory(
        scan_projections(roots),
        digest_index=digest_index,
        rights_for=_rights_for,
        receipt_index=receipt_index,
        declared_provenance=declared,
    )
    document = inventory_document(classifications, observed_at=observed_at)
    document["_classifications"] = classifications
    document["roots"] = [str(root) for root in roots]
    document["receipt_stores_read"] = [str(store.path) for store in stores]
    document["locks_read"] = read_locks
    document["digest_index_size"] = len(digest_index)
    return document


def enforce_classifications(
    classifications: Sequence[Any],
    *,
    register_path: Path,
    recorded_at: str,
) -> tuple[str, ...]:
    """Write every non-compliant classification into the durable register.

    Without this the inventory and the enforcement state are two unrelated
    facts: the report named 38 non-compliant projections and nothing on the
    machine would refuse to overwrite one, because no production path ever
    called `NonComplianceRegister.record`. Review demonstrated a sync
    overwriting a projection this report had just classified.

    A report that describes a control nobody armed is worse than no report,
    because it reads as evidence that the control ran.
    """
    register = NonComplianceRegister(Path(register_path))
    recorded: list[str] = []
    for classification in classifications:
        if not classification.blocks_rematerialization():
            continue
        register.record(classification, recorded_at=recorded_at)
        recorded.append(classification.projection.path)
    return tuple(recorded)


_HEADER = """# Legacy projection inventory (ADR-0011, `CL-m6cc` AC5)

> **Generated. Do not edit.** Regenerate with
> `uv run python scripts/checks/legacy_projection_inventory.py`. Use `--output-json`
> when a machine-readable artifact is needed for an explicit audit.

This inventory replaces the name-matched survey in ADR-0011
`Legacy Projection Disposition`. Provenance here is derived **only** from a
normalized content digest matching a digest a provider actually served. A shared
name attributes nothing, and a Library-shaped bridge without a Library receipt is
not Library-owned.

A projection whose digest matches nothing is recorded
`rights-unresolved-pending-digest-attribution`. That is **non-compliant** in the
ADR's sense, which means exactly two things and no more:

- it may not be re-materialized by any later sync or repair, and
- it has an explicit remediation path an operator must choose.

It keeps every byte it has. Migration grants no deletion authority.
"""


def render_markdown(document: Mapping[str, Any]) -> str:
    """Render one inventory document. Deterministic, so the artifact is checkable."""
    counts = document["counts"]
    lines = [_HEADER, ""]
    lines.append(f"- Observed at: `{document['observed_at']}`")
    lines.append(
        "- Roots: " + ", ".join(f"`{root}`" for root in document.get("roots", []))
    )
    stores = document.get("receipt_stores_read") or []
    lines.append(
        "- Foreign receipt stores read: "
        + (", ".join(f"`{store}`" for store in stores) if stores else "none found")
    )
    locks = document.get("locks_read") or []
    lines.append(
        "- Existing locks read for declared provenance: "
        + (", ".join(f"`{lock}`" for lock in locks) if locks else "none found")
    )
    lines.append(f"- Resolved upstream digests available: {document['digest_index_size']}")
    register = document.get("register_path")
    lines.append(
        f"- Non-compliance register armed: `{register}` "
        f"({document.get('registered_non_compliant', 0)} entries recorded)"
        if register
        else "- Non-compliance register armed: no (report-only run)"
    )
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append("| Measure | Count |")
    lines.append("|---|---|")
    for key in (
        "total",
        "attributed",
        "unattributed",
        "receipted",
        "unreceipted",
        "compliant",
        "non_compliant",
    ):
        lines.append(f"| `{key}` | {counts[key]} |")
    lines.append("")
    lines.append("## Entries")
    lines.append("")
    lines.append(
        "| Name | Kind | Members | Provenance | Redistribution | Receipt | Compliance | State |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for entry in document["entries"]:
        lines.append(
            "| `{name}` | {kind} | {members} | {provenance} | {redistribution} | "
            "{receipt} | {compliance} | {state} |".format(
                name=entry["name"],
                kind=entry["kind"],
                members=entry["member_count"],
                provenance=entry["provenance_state"],
                redistribution=entry["redistribution_state"],
                receipt=entry["receipt_status"],
                compliance=entry["compliance"],
                state=entry["pending_reason"] or "-",
            )
        )
    lines.append("")
    lines.append("## Digests")
    lines.append("")
    lines.append("| Name | Path | Normalized content digest | Link target |")
    lines.append("|---|---|---|---|")
    for entry in document["entries"]:
        lines.append(
            "| `{name}` | `{path}` | `{digest}` | {link} |".format(
                name=entry["name"],
                path=entry["path"],
                digest=entry["content_digest"],
                link=f"`{entry['link_target']}`" if entry["link_target"] else "-",
            )
        )
    lines.append("")
    lines.append("## Remediation")
    lines.append("")
    lines.append(
        "Every non-compliant entry above carries both ADR-0011 remediation paths: "
        "`operator-confirmed-removal` and `relocate-machine-local`. Neither runs "
        "automatically. `scripts/lib/providers/legacy_projections.py` issues the "
        "statement and accepts only a confirmation bound to that statement, so a "
        "remediation cannot happen without the operator having been shown what it "
        "affects."
    )
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="legacy-projection-inventory",
        description="Derive the ADR-0011 legacy projection inventory by content digest.",
    )
    parser.add_argument("--root", action="append", default=None, metavar="PATH")
    parser.add_argument("--receipts", action="append", default=None, metavar="PATH")
    parser.add_argument("--lock", action="append", default=None, metavar="PATH")
    parser.add_argument("--digest-index", default=None, metavar="PATH")
    parser.add_argument("--output-json", default=str(JSON_ARTIFACT), metavar="PATH")
    parser.add_argument("--output-markdown", default=str(MARKDOWN_ARTIFACT), metavar="PATH")
    parser.add_argument("--observed-at", default=None, metavar="TIMESTAMP")
    parser.add_argument(
        "--register",
        default=str(DEFAULT_REGISTER),
        metavar="PATH",
        help="Durable non-compliance register to arm with this inventory.",
    )
    parser.add_argument(
        "--no-enforce",
        action="store_true",
        default=False,
        help="Report only; do not record classifications into the register.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots = [Path(item).expanduser() for item in (args.root or [])] or list(DEFAULT_ROOTS)
    receipts = [Path(item).expanduser() for item in (args.receipts or [])] or list(
        DEFAULT_RECEIPT_STORES
    )
    locks = [Path(item).expanduser() for item in (args.lock or [])] or list(DEFAULT_LOCKS)
    observed_at = args.observed_at or _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    document = build_document(
        roots=roots,
        digest_index=load_digest_index(
            Path(args.digest_index).expanduser() if args.digest_index else None
        ),
        receipt_store_paths=receipts,
        lock_paths=locks,
        observed_at=observed_at,
    )

    classifications = document.pop("_classifications")
    if not args.no_enforce:
        armed = enforce_classifications(
            classifications,
            register_path=Path(args.register).expanduser(),
            recorded_at=observed_at,
        )
        document["register_path"] = str(Path(args.register).expanduser())
        document["registered_non_compliant"] = len(armed)
    else:
        document["register_path"] = None
        document["registered_non_compliant"] = 0

    json_path = Path(args.output_json)
    markdown_path = Path(args.output_markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(document), encoding="utf-8")

    counts = document["counts"]
    print(
        f"{INVENTORY_SCHEMA}: {counts['total']} projection(s), "
        f"{counts['unattributed']} unattributed, {counts['non_compliant']} non-compliant "
        f"({PENDING_DIGEST_ATTRIBUTION} where unattributed)"
    )
    print(f"wrote {json_path}")
    print(f"wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
