"""`library.yaml` provider-registration fields (CL-coif AC5).

ADR-0011 extends `sources.marketplaces` with the four fields a heterogeneous
provider needs: `provider_kind`, `allowlist`, `auth_ref`, and `rights`. The
schema is the contract for a catalog *file*; `lib.providers.registration` is
the contract for the API. `test_registration_and_schema_agree_on_provider_kinds`
holds them to the same vocabulary so they cannot drift apart.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

jsonschema = pytest.importorskip("jsonschema")
yaml = pytest.importorskip("yaml")

from lib.providers.registration import (  # noqa: E402
    PROVIDER_KINDS,
    RegistrationError,
    register_provider,
)

SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"
LIBRARY_PATH = REPO_ROOT / "library.yaml"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def marketplace_schema() -> dict:
    return load_schema()["$defs"]["marketplace_entry"]


def _validate(entry: dict) -> list[str]:
    """Validate one entry with the whole document as the reference root."""
    schema = load_schema()
    validator = jsonschema.Draft202012Validator(
        {
            "$schema": schema.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
            "$ref": "#/$defs/marketplace_entry",
            "$defs": schema["$defs"],
        }
    )
    return [error.message for error in validator.iter_errors(entry)]


def _entry(**overrides: object) -> dict:
    base: dict = {
        "name": "mattpocock",
        "source": "https://github.com/mattpocock/skills",
        "type": "git",
    }
    base.update(overrides)
    return base


def test_provider_kind_validation() -> None:
    """Every ADR-0011 provider kind is accepted; an unknown one is rejected."""
    for kind in ("git-repo", "git-org", "mcp-content", "hosted-index"):
        entry = _entry(provider_kind=kind)
        if kind == "git-org":
            entry["allowlist"] = ["pi-vs-claude-code"]
        assert _validate(entry) == [], (kind, _validate(entry))

    errors = _validate(_entry(provider_kind="carrier-pigeon"))
    assert errors, "an unknown provider_kind must be rejected"
    assert any("carrier-pigeon" in message for message in errors)


def test_git_org_requires_allowlist() -> None:
    """Organization-level enumeration without an allowlist is refused."""
    errors = _validate(_entry(source="https://github.com/disler", provider_kind="git-org"))
    assert errors, "a git-org entry without an allowlist must be rejected"
    assert any("allowlist" in message for message in errors)

    assert (
        _validate(
            _entry(
                source="https://github.com/disler",
                provider_kind="git-org",
                allowlist=["pi-vs-claude-code", "fusion-harness", "planf3"],
            )
        )
        == []
    )

    empty = _validate(
        _entry(source="https://github.com/disler", provider_kind="git-org", allowlist=[])
    )
    assert empty, "an empty allowlist is not an allowlist"


def test_allowlist_is_only_meaningful_with_a_provider_kind() -> None:
    """A `git-repo` entry may carry no allowlist and still validate."""
    assert _validate(_entry(provider_kind="git-repo")) == []


def test_auth_ref_is_a_named_reference() -> None:
    assert _validate(_entry(provider_kind="mcp-content", auth_ref="executive-circle-token")) == []
    assert _validate(_entry(provider_kind="mcp-content", auth_ref="")) != []


def test_rights_accepts_the_four_independent_grants() -> None:
    entry = _entry(
        provider_kind="git-repo",
        rights={
            "fetch_authorization": "granted",
            "install_rights": "granted",
            "redistribution_rights": "granted",
            "derivative_rights": "granted",
            "evidence_source": "upstream LICENSE (MIT), verified 2026-08-08",
        },
    )
    assert _validate(entry) == []

    assert _validate(_entry(rights={"fetch_authorization": "probably"})) != []
    assert _validate(_entry(rights={"resale_rights": "granted"})) != []


def test_unknown_is_a_legal_rights_state() -> None:
    """`unknown` is the conservative default, not an invalid value."""
    assert (
        _validate(
            _entry(
                provider_kind="mcp-content",
                source="mcp:executive-circle",
                rights={
                    "fetch_authorization": "granted",
                    "install_rights": "unknown",
                    "redistribution_rights": "unknown",
                    "derivative_rights": "unknown",
                },
            )
        )
        == []
    )


def test_registration_and_schema_agree_on_provider_kinds() -> None:
    """The API vocabulary and the file vocabulary are the same vocabulary."""
    schema_kinds = tuple(marketplace_schema()["properties"]["provider_kind"]["enum"])
    assert schema_kinds == PROVIDER_KINDS


def test_registration_enforces_the_same_git_org_rule() -> None:
    catalog: dict = {"sources": {"marketplaces": []}}
    with pytest.raises(RegistrationError):
        register_provider(
            catalog,
            _entry(source="https://github.com/disler", name="disler", provider_kind="git-org"),
        )
    assert catalog["sources"]["marketplaces"] == []


def test_live_library_yaml_still_validates() -> None:
    """The new fields are additive: the committed catalog keeps validating."""
    data = yaml.safe_load(LIBRARY_PATH.read_text())
    validator = jsonschema.Draft202012Validator(load_schema())
    errors = [
        f"[{'/'.join(str(part) for part in error.absolute_path)}] {error.message}"
        for error in validator.iter_errors(data)
    ]
    assert errors == [], "\n".join(errors)
