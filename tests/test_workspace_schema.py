from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (REPO_ROOT / "docs" / "schema" / "workspace.schema.json").read_text()
)


@pytest.fixture
def manifest() -> dict:
    return {
        "schema_version": 1,
        "name": "python-cli",
        "version": "1.0.0",
        "description": "Shared Python CLI development baseline",
        "status": "experimental",
        "roots": [
            {"type": "skill", "name": "python-dev", "constraint": ">=1.0.0,<2.0.0"},
            {"type": "skill", "name": "python-test", "constraint": ">=1.0.0,<2.0.0"},
        ],
    }


def test_workspace_manifest_accepts_two_same_catalog_artifact_roots(
    manifest: dict,
) -> None:
    jsonschema.validate(manifest, SCHEMA)


@pytest.mark.parametrize(
    "bad_root",
    [
        {"type": "workspace", "name": "nested"},
        {"type": "package", "name": "legacy"},
        {"type": "skill", "name": "python-dev", "catalog": "another"},
    ],
)
def test_workspace_manifest_rejects_v1_composition_expansion(
    manifest: dict, bad_root: dict
) -> None:
    candidate = deepcopy(manifest)
    candidate["roots"][0] = bad_root
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, SCHEMA)


def test_workspace_manifest_rejects_one_member_alias(manifest: dict) -> None:
    candidate = deepcopy(manifest)
    candidate["roots"] = candidate["roots"][:1]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, SCHEMA)


def test_workspace_manifest_rejects_partial_semver_constraint(manifest: dict) -> None:
    candidate = deepcopy(manifest)
    candidate["roots"][0]["constraint"] = ">=1,<2"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, SCHEMA)


def test_workspace_manifest_rejects_duplicate_roots(manifest: dict) -> None:
    candidate = deepcopy(manifest)
    candidate["roots"][1] = deepcopy(candidate["roots"][0])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, SCHEMA)
