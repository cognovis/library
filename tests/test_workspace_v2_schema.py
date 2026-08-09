"""Workspace schema v2 validation (CL-dbam AC2, AC9).

ADR-0011 `Qualified roots` puts the whole cross-catalog trust boundary in one
reviewable place: the pinned `catalogs:` block is the only location a Workspace
may name a source, and a root references it by manifest-local alias. Every
negative case here is one way that boundary could be dissolved -- an unpinned
catalog that follows a moving branch, a root that names its own source, an alias
nothing declares, and a v2 qualifier smuggled into a v1 manifest that no v2 rule
governs.

Both layers are asserted for every case. The JSON Schema is what an author's
editor and `library workspace validate` check; `validate_workspace_manifest` is
what resolution checks. A rule enforced in only one of them is a rule an
attacker picks the other door for.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.errors import LibraryError  # noqa: E402
from lib.workspace import validate_workspace_manifest  # noqa: E402
from workspace_v2_fixtures import v1_manifest, v2_manifest  # noqa: E402

SCHEMA = json.loads(
    (REPO_ROOT / "docs" / "schema" / "workspace.schema.json").read_text()
)


def _refuses(manifest: dict, match: str) -> None:
    """Both the document schema and the resolver validator must refuse."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, SCHEMA)
    with pytest.raises(LibraryError, match=match):
        validate_workspace_manifest(manifest)


def test_accepts_pinned_cross_catalog_manifest() -> None:
    manifest = v2_manifest()

    jsonschema.validate(manifest, SCHEMA)
    validate_workspace_manifest(manifest)


def test_v1_manifest_remains_valid_and_unchanged() -> None:
    manifest = v1_manifest()

    jsonschema.validate(manifest, SCHEMA)
    validate_workspace_manifest(manifest)
    assert manifest == v1_manifest()


def test_rejects_unpinned_catalog() -> None:
    """An unpinned catalog resolves from a moving ref, which is the redirect."""
    missing = v2_manifest()
    del missing["catalogs"][1]["pin"]
    _refuses(missing, "pin")

    empty = v2_manifest()
    empty["catalogs"][1]["pin"] = {}
    _refuses(empty, "pin")

    moving = v2_manifest()
    moving["catalogs"][1]["pin"] = {"kind": "commit", "value": "main"}
    _refuses(moving, "pin")


def test_rejects_url_in_root() -> None:
    """A root may reference an alias. It may never name a source itself."""
    qualified_with_url = v2_manifest()
    qualified_with_url["roots"][1]["catalog"] = "https://example.invalid/upstream"
    _refuses(qualified_with_url, "alias")

    carries_source = v2_manifest()
    carries_source["roots"][1]["source"] = "https://example.invalid/upstream"
    _refuses(carries_source, "source")

    carries_identity = v2_manifest()
    carries_identity["roots"][1]["identity"] = "https://example.invalid/upstream"
    _refuses(carries_identity, "identity")


def test_rejects_undeclared_alias() -> None:
    manifest = v2_manifest()
    manifest["roots"][1]["catalog"] = "not-declared"

    jsonschema.validate(manifest, SCHEMA)  # shape is fine; the binding is not
    with pytest.raises(LibraryError, match="not declared"):
        validate_workspace_manifest(manifest)


def test_rejects_duplicate_catalog_alias() -> None:
    manifest = v2_manifest()
    manifest["catalogs"][1]["alias"] = "core"

    with pytest.raises(LibraryError, match="duplicate"):
        validate_workspace_manifest(manifest)


def test_rejects_qualifier_in_v1() -> None:
    """A v1 manifest has no `catalogs:` block, so a qualifier binds to nothing."""
    qualified = v1_manifest()
    qualified["roots"][0]["catalog"] = "core"
    _refuses(qualified, "schema_version 2")

    declares_catalogs = v1_manifest()
    declares_catalogs["catalogs"] = deepcopy(v2_manifest()["catalogs"])
    _refuses(declares_catalogs, "catalogs")


def test_rejects_nested_workspace() -> None:
    """Nested Workspaces stay deferred under ADR-0010's unamended gate."""
    for manifest in (v1_manifest(), v2_manifest()):
        nested = deepcopy(manifest)
        nested["roots"][0] = {"type": "workspace", "name": "engineering"}
        if nested["schema_version"] == 2:
            nested["roots"][0]["catalog"] = "core"
        _refuses(nested, "[Nn]ested")


def test_rejects_v2_manifest_without_catalogs() -> None:
    manifest = v2_manifest()
    del manifest["catalogs"]

    _refuses(manifest, "catalogs")


def test_rejects_unknown_pin_kind() -> None:
    manifest = v2_manifest()
    manifest["catalogs"][1]["pin"] = {"kind": "branch", "value": "b" * 64}

    _refuses(manifest, "pin")


def test_rejects_unsupported_schema_version() -> None:
    manifest = v2_manifest()
    manifest["schema_version"] = 3

    _refuses(manifest, "schema_version")
