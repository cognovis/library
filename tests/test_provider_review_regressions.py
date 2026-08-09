"""Every reviewer proof-of-concept from the CL-mvet review, as a regression test.

Wave 1 of the adversarial review produced six blocking findings and four
advisories, each demonstrated by an executed counterexample rather than by
reading. This file re-executes every one of those counterexamples against the
delivered candidate, so a repair that only moves the problem fails here rather
than in the next slice.

It is also the compensating evidence for a co-reviewer that could not run: the
second mandated reviewer refused with a provider quota error before its first
turn, so the demonstrations that *did* run are held permanently instead of being
read once and discarded.

Each test names the finding it holds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.admission import AdmissionContext, evaluate_item  # noqa: E402
from lib.providers.cache_transaction import IncompleteRetrieval  # noqa: E402
from lib.providers.classification import UNCLASSIFIED  # noqa: E402
from lib.providers.contract import (  # noqa: E402
    AuthRequirement,
    Availability,
    FetchedFile,
    FetchedItem,
    ProviderItem,
    REQUIRED_CAPABILITIES,
    SourceProvider,
)
from lib.providers.decompose import (  # noqa: E402
    AmbiguousItemLayout,
    BUNDLE_LAYOUT,
    MARKER_LAYOUT,
    decompose_tree,
)
from lib.providers.inventory import (  # noqa: E402
    NormalizedItem,
    ProviderAvailability,
    Rights,
)
from lib.providers.mcp_content import (  # noqa: E402
    CredentialValueRefused,
    McpContentProvider,
)
from lib.providers.rights import ProjectionRefused  # noqa: E402
from lib.providers.wiring import (  # noqa: E402
    ForeignState,
    ProjectionEscape,
    completeness_for,
    filesystem_activation,
    install_marketplace_item,
)
from lib.routing import (  # noqa: E402
    ContextPointer,
    RoutingAnswer,
    RoutingNotCatalogDerived,
)

LIBRARY_PY = REPO_ROOT / "scripts" / "library.py"

MIT_EVIDENCE = "upstream LICENSE (MIT) observed in the pinned tree, 2026-08-09"


def _granted() -> Rights:
    return Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source=MIT_EVIDENCE,
    )


def _item(
    *,
    library_type: str = "skill",
    name: str = "example",
    rights: Rights | None = None,
    classification: Mapping[str, str] | None = None,
) -> NormalizedItem:
    return NormalizedItem(
        provider_identity="https://example.invalid/provider",
        upstream_id=f"items/{name}",
        upstream_name=name,
        collection_membership=("items",),
        upstream_revision="a" * 40,
        library_type=library_type,
        library_name=name,
        classification=dict(
            classification or {"type_basis": "marker-file", "maturity": "stable"}
        ),
        runtime_compatibility=("unknown",),
        rights=rights or _granted(),
        provider_availability=ProviderAvailability(
            state="available", observed_at="2026-08-09T12:00:00Z"
        ),
    )


class _StubProvider(SourceProvider):
    """A minimal adapter whose capability declaration the test controls."""

    def __init__(
        self,
        *,
        files: Mapping[str, bytes],
        manifest: tuple[str, ...] | None = None,
        declares_manifest: bool = True,
    ) -> None:
        self._files = dict(files)
        self._manifest = manifest
        self._declares_manifest = declares_manifest

    def identity(self) -> str:
        return "https://example.invalid/provider"

    def capabilities(self) -> frozenset[str]:
        declared = set(REQUIRED_CAPABILITIES)
        if self._declares_manifest:
            declared.add("member_manifest")
        return frozenset(declared)

    def enumerate(self, selector: Any = None):
        return (ProviderItem(upstream_id="items/example", upstream_name="example"),)

    def fetch(self, upstream_id: str, revision: str | None = None) -> FetchedItem:
        return FetchedItem(
            upstream_id=upstream_id,
            revision=revision or "a" * 40,
            files=tuple(
                FetchedFile(path=path, content=content)
                for path, content in sorted(self._files.items())
            ),
            primary_path=sorted(self._files)[0],
        )

    def auth_requirements(self):
        return (AuthRequirement(reference="none", scope="read", required=False),)

    def availability(self) -> Availability:
        return Availability(state="available", observed_at="2026-08-09T12:00:00Z")

    def member_manifest(self, upstream_id: str, revision: str | None = None):
        return self._manifest if self._manifest is not None else tuple(sorted(self._files))


def _state(tmp_path: Path) -> ForeignState:
    for scope in ("project", "global"):
        (tmp_path / scope).mkdir(parents=True, exist_ok=True)
    return ForeignState.for_locks(
        cache_root=tmp_path / "cache",
        project_lock=tmp_path / "project" / ".library.lock",
        global_lock=tmp_path / "global" / "global.lock",
    )


# ---------------------------------------------------------------------------
# F1 — the install command treated `discoverable` as installable
# ---------------------------------------------------------------------------


def test_f1_an_in_progress_item_is_not_installable_through_the_command() -> None:
    """An `in-progress` item resolves to `discoverable`, and the CLI refuses it.

    The gap review demonstrated was between the two: the inventory decided
    `discoverable` correctly and the install command accepted anything that was
    not `blocked`, so an unpromoted item was projected and receipted.
    """
    item = _item(
        classification={
            "type_basis": "marker-file",
            "maturity": "in-progress",
            "maturity_basis": "collection:in-progress",
        }
    )
    decision = evaluate_item(item, AdmissionContext())
    assert decision.admission_state == "discoverable"
    assert decision.block_reasons == ()

    source = LIBRARY_PY.read_text()
    assert 'if decision.admission_state != "installable":' in source, (
        "the install command gates on installable, not on the absence of a block"
    )


def test_f1_an_unclassified_member_is_not_installable_through_the_command() -> None:
    """The same gate covers the other discoverable state."""
    item = _item(library_type=UNCLASSIFIED, name="notes-html")
    decision = evaluate_item(item, AdmissionContext())
    assert decision.admission_state == "discoverable"
    assert set(decision.projection_eligibility.values()) == {"blocked"}


# ---------------------------------------------------------------------------
# F3 — a projection escaped its target root through a symlink
# ---------------------------------------------------------------------------


def test_f3_a_projection_cannot_escape_through_a_symlink(tmp_path: Path) -> None:
    """A pre-existing symlink under the root no longer redirects the write.

    Review created `target/link` pointing outside the root and activated
    `link/escaped.txt`: plan and apply agreed on the declared string while the
    bytes landed elsewhere. Both phases now refuse.
    """
    root = tmp_path / "target"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside)

    activation = filesystem_activation(root)
    content = {"link/escaped.txt": b"escaped"}

    with pytest.raises(ProjectionEscape):
        activation.plan(content)
    with pytest.raises(ProjectionEscape):
        activation.apply(content)
    assert not (outside / "escaped.txt").exists()


def test_f3_a_traversal_member_is_refused(tmp_path: Path) -> None:
    """The same containment check covers a relative path leaving the root."""
    root = tmp_path / "target"
    root.mkdir()
    activation = filesystem_activation(root)
    with pytest.raises(ProjectionEscape):
        activation.plan({"../escaped.txt": b"escaped"})


def test_f3_a_contained_projection_still_works(tmp_path: Path) -> None:
    """Containment refuses escapes without refusing ordinary nested members."""
    root = tmp_path / "target"
    root.mkdir()
    activation = filesystem_activation(root)
    content = {"SKILL.md": b"body\n", "agents/openai.yaml": b"agent\n"}
    planned = list(activation.plan(content))
    created = activation.apply(content)
    assert sorted(target.path for target in created) == sorted(planned)
    assert (root / "agents" / "openai.yaml").read_bytes() == b"agent\n"


# ---------------------------------------------------------------------------
# F4 — nested marker directories claimed the same bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("layout", [MARKER_LAYOUT, BUNDLE_LAYOUT])
def test_f4_nested_marker_items_are_refused(layout: str) -> None:
    """`outer/SKILL.md` beside `outer/child/AGENT.md` is an ownership collision.

    The outer item owns every path beneath its directory, so the two items claim
    the same bytes and the cache would hold one artifact under two identities.
    """
    paths = ["outer/SKILL.md", "outer/child/AGENT.md", "outer/child/body.txt"]
    with pytest.raises(AmbiguousItemLayout, match="nested inside"):
        decompose_tree(paths, layout=layout, root_name="repository")


def test_f4_sibling_marker_items_are_unaffected() -> None:
    """Refusing nesting does not refuse the ordinary sibling layout."""
    items = decompose_tree(
        [
            "skills/one/SKILL.md",
            "skills/one/agents/openai.yaml",
            "skills/two/SKILL.md",
        ],
        layout=MARKER_LAYOUT,
        root_name="repository",
    )
    assert [item.upstream_id for item in items] == ["skills/one", "skills/two"]
    claimed = [path for item in items for path in item.member_paths]
    assert len(claimed) == len(set(claimed)), "no path is owned by two items"


# ---------------------------------------------------------------------------
# F5 — a declared but empty member manifest was silently discarded
# ---------------------------------------------------------------------------


def test_f5_an_empty_declared_manifest_is_a_refusal_not_a_downgrade() -> None:
    """A declared manifest that lists nothing is an adapter defect, not absence.

    Downgrading it to the adapter's own word discarded the manifest and recorded
    the false reason that the capability was not declared, so a nonempty
    retrieval installed against a manifest it never had to match.
    """
    provider = _StubProvider(files={"SKILL.md": b"body\n"}, manifest=())
    with pytest.raises(IncompleteRetrieval, match="declares member_manifest"):
        completeness_for(provider, _item())


def test_f5_a_declared_manifest_is_checked_against_the_retrieval() -> None:
    """A manifest that disagrees with the fetch refuses the install."""
    evidence = completeness_for(
        _StubProvider(files={"SKILL.md": b"body\n"}, manifest=("SKILL.md", "EXTRA.md")),
        _item(),
    )
    assert evidence.method == "member-manifest"
    with pytest.raises(IncompleteRetrieval, match="member manifest"):
        evidence.check(["SKILL.md"], "https://example.invalid/provider#items/example")


def test_f5_an_undeclared_manifest_records_the_weaker_evidence() -> None:
    """An adapter that cannot list members says so explicitly."""
    evidence = completeness_for(
        _StubProvider(files={"SKILL.md": b"body\n"}, declares_manifest=False), _item()
    )
    assert evidence.method == "adapter-declaration"
    assert "does not declare member_manifest" in evidence.detail


# ---------------------------------------------------------------------------
# F6 — durable retention was never gated by install_rights
# ---------------------------------------------------------------------------


def test_f6_denied_install_rights_leaves_no_cache_object(tmp_path: Path) -> None:
    """`install_rights: denied` forbids durable retention, so nothing is written.

    Review found a cache object and a receipt left behind a refused projection:
    the transaction materializes and receipts before it evaluates projection, and
    nothing evaluated retention at all.
    """
    denied = Rights(
        fetch_authorization="granted",
        install_rights="denied",
        redistribution_rights="denied",
        derivative_rights="denied",
        evidence_source="upstream licence forbids local redistribution, 2026-08-09",
    )
    state = _state(tmp_path)
    with pytest.raises(ProjectionRefused):
        install_marketplace_item(
            _item(rights=denied),
            provider=_StubProvider(files={"SKILL.md": b"body\n"}),
            state=state,
            scope="project",
            target="machine_local",
            target_root=tmp_path / "projection",
        )
    assert state.object_store().objects() == ()
    assert state.receipt_store("project").all() == ()
    assert not (tmp_path / "projection").exists()


def test_f6_unknown_install_rights_needs_a_shown_opt_in(tmp_path: Path) -> None:
    """`unknown` retention is acknowledged after the statement is shown."""
    unknown = Rights(
        fetch_authorization="granted",
        install_rights="unknown",
        redistribution_rights="unknown",
        derivative_rights="unknown",
        evidence_source="no published licence located, 2026-08-09",
    )
    state = _state(tmp_path)

    # No presenter: the act is refused and nothing is retained.
    with pytest.raises(ProjectionRefused):
        install_marketplace_item(
            _item(rights=unknown),
            provider=_StubProvider(files={"SKILL.md": b"body\n"}),
            state=state,
            scope="project",
            target="machine_local",
            target_root=tmp_path / "projection",
        )
    assert state.object_store().objects() == ()
    assert state.receipt_store("project").all() == ()

    # With a presenter, the retention statement is shown before the projection
    # statement, because retaining the bytes is the earlier act.
    shown: list[str] = []

    def present(presentation):
        shown.append(presentation.statement)
        return presentation.acknowledge(
            operator="test-operator", acknowledged_at="2026-08-09T12:00:00Z"
        )

    install_marketplace_item(
        _item(rights=unknown),
        provider=_StubProvider(files={"SKILL.md": b"body\n"}),
        state=state,
        scope="project",
        target="machine_local",
        target_root=tmp_path / "projection",
        present=present,
    )
    assert len(shown) == 2
    assert "install_rights" in shown[0]
    assert state.receipt_store("project").all(), "the acknowledged install is retained"


# ---------------------------------------------------------------------------
# A1 — a token-shaped value passed as a credential reference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "sk-prod-0123456789abcdef",
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "ec0123456789abcdef0123456789abcdef",
        "Bearer ec-live-2f5a9c41d7e84b0fa6c3e19b7d520148",
    ],
)
def test_a1_credential_shaped_references_are_refused(value: str) -> None:
    """A reference is a name; these are values, and each was accepted before."""
    with pytest.raises(CredentialValueRefused):
        McpContentProvider(server_name="example", auth_ref=value)


@pytest.mark.parametrize(
    "value", ["executive-circle-subscriber", "acme.api.token_ref", "team/shared-key"]
)
def test_a1_ordinary_references_are_still_accepted(value: str) -> None:
    """The raised floor refuses values without refusing plausible names."""
    provider = McpContentProvider(server_name="example", auth_ref=value)
    assert provider.auth_requirements()[0].reference == value


# ---------------------------------------------------------------------------
# A2 — a routing note named an unread source in plain prose
# ---------------------------------------------------------------------------


def test_a2_a_note_naming_an_unread_source_in_plain_prose_is_refused() -> None:
    """A bare repository name in a note is the likeliest routing-table leak.

    The URL scan could not see it. Notes are now checked by provenance instead:
    only prose this module generated may appear.
    """
    smuggled = RoutingAnswer(
        query="which skill reviews a bead",
        candidates=(),
        catalogs_read=(),
        identities_read=(),
        context_pointers=(ContextPointer(label="rules", path=Path("/x"), present=False),),
        notes=("try sussdorff-core, it usually has the reviewer skills",),
    )
    with pytest.raises(RoutingNotCatalogDerived, match="did not generate"):
        smuggled.assert_catalog_derived()


def test_a2_generated_notes_still_pass() -> None:
    """The provenance check does not refuse the module's own notes."""
    answer = RoutingAnswer(
        query="which skill reviews a bead",
        candidates=(),
        catalogs_read=(),
        identities_read=(),
        context_pointers=(),
        notes=(
            "no source is registered on this machine, so no candidate can be "
            "attributed to one",
        ),
    )
    assert answer.assert_catalog_derived() is answer


# ---------------------------------------------------------------------------
# F2 — the Workspace mutation wrote bytes the gate never admitted
# ---------------------------------------------------------------------------


def _v2_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A project publishing one cross-catalog v2 Workspace over real repositories."""
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()

    core = project / "team-core"
    upstream = project / "upstream-core"
    for root, names in ((core, ("python-dev",)), (upstream, ("helper",))):
        for name in names:
            skill = root / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\nversion: 1.0.0\n---\n# {name}\n"
            )

    heads = {}
    for alias, root in (("core", core), ("upstream", upstream)):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for command in (
            ["git", "config", "user.email", "test@example.invalid"],
            ["git", "config", "user.name", "Test"],
            ["git", "add", "-A"],
            ["git", "commit", "-q", "-m", "catalog content"],
        ):
            subprocess.run(command, cwd=root, check=True)
        heads[alias] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    manifest = {
        "schema_version": 2,
        "name": "engineering",
        "version": "1.0.0",
        "description": "Engineering baseline across two catalogs.",
        "status": "experimental",
        "catalogs": [
            {
                "alias": "core",
                "identity": "https://example.invalid/core",
                "pin": {"kind": "commit", "value": heads["core"]},
            },
            {
                "alias": "upstream",
                "identity": "https://example.invalid/upstream",
                "pin": {"kind": "commit", "value": heads["upstream"]},
            },
        ],
        "roots": [
            {"type": "skill", "name": "python-dev", "catalog": "core"},
            {"type": "skill", "name": "helper", "catalog": "upstream"},
        ],
    }
    workspaces = core / "workspaces"
    workspaces.mkdir()
    (workspaces / "engineering.yaml").write_text(yaml.safe_dump(manifest))

    catalog = {
        "catalog_identity": "https://example.invalid/platform",
        "default_dirs": {
            "skills": [{"default": ".agents/skills/", "global": "~/.agents/skills/"}]
        },
        "sources": {
            "catalogs": [
                {
                    "name": "team-core",
                    "source": "https://example.invalid/core",
                    "local_path": str(core),
                    "content_types": ["skills", "workspaces"],
                },
                {
                    "name": "upstream-core",
                    "source": "https://example.invalid/upstream",
                    "local_path": str(upstream),
                    "content_types": ["skills"],
                },
            ],
            "marketplaces": [],
        },
        "library": {
            "skills": [
                {
                    "name": "python-dev",
                    "description": "python-dev skill.",
                    "version": "1.0.0",
                    "source": str(core / "skills" / "python-dev" / "SKILL.md"),
                    "metadata": {"library": {"source_catalog": "team-core"}},
                },
                {
                    "name": "helper",
                    "description": "helper skill.",
                    "version": "1.0.0",
                    "source": str(upstream / "skills" / "helper" / "SKILL.md"),
                    "metadata": {"library": {"source_catalog": "upstream-core"}},
                },
            ],
            "workspaces": [
                {
                    **manifest,
                    "source": str(workspaces / "engineering.yaml"),
                    "metadata": {
                        "library": {
                            "source_catalog": "team-core",
                            "inventory": "convention-scan",
                        }
                    },
                }
            ],
        },
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    return project, home, upstream / "skills" / "helper" / "SKILL.md"


def test_f2_the_workspace_write_path_refuses_bytes_the_gate_did_not_admit(
    tmp_path: Path,
) -> None:
    """A member's source edited after the gate digested it fails the operation.

    Review changed `helper/SKILL.md` immediately after the gate captured the
    bytes; the command returned 0 and installed the changed bytes, so the
    admission decision described a payload that was never written.

    The legacy installers resolve their own source and cannot be handed the
    frozen mapping, so the binding is enforced by comparison instead: the
    admitted snapshot is re-derived and compared immediately before the write.
    """
    project, home, helper_source = _v2_project(tmp_path)

    environment = os.environ.copy()
    environment["HOME"] = str(home)
    baseline = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "workspace", "use", "team-core:engineering",
         "--scope", "project", "--json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr

    # The comparison itself, exercised directly: an admitted snapshot that no
    # longer matches the source is reported as drift, by identity.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import importlib

    library = importlib.import_module("library")
    from lib.catalog import load_catalog
    from lib.workspace import resolve_workspace, resolve_workspace_closure

    catalog = load_catalog(project)
    workspace = resolve_workspace(catalog, "team-core:engineering")
    closure = resolve_workspace_closure(
        catalog,
        workspace,
        project,
        "project",
        pin_verifier=library._workspace_pin_verifier(catalog),
    )
    _, admitted = library._workspace_normalized_members(catalog, closure, project)
    assert admitted, "the closure normalized into content-bearing items"
    assert library._workspace_gated_content_drift(catalog, closure, project, admitted) == []

    helper_source.write_text("---\nname: helper\nversion: 1.0.0\n---\n# changed\n")
    drifted = library._workspace_gated_content_drift(catalog, closure, project, admitted)
    assert drifted, "an edited source is reported as drift against the admitted bytes"
    assert any("helper" in identity for identity in drifted)


def test_f2_the_install_callback_receives_and_uses_the_frozen_content() -> None:
    """The mutation callback consumes the gate's content instead of ignoring it."""
    source = LIBRARY_PY.read_text()
    assert "def _install_members(frozen_content=None) -> None:" in source
    assert "_workspace_gated_content_drift(" in source
    assert "def _install_members(_frozen_content=None)" not in source, (
        "an unused parameter is the tell that the gate's bytes bind nothing"
    )


# ---------------------------------------------------------------------------
# A4 — the drawdown claim, held to what it actually proves
# ---------------------------------------------------------------------------


def test_a4_the_drawdown_claim_is_stated_as_knowledge_not_independence() -> None:
    """`source.py` scans clean and is still a Git-only path; both are recorded."""
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "checks"))
    import provider_neutrality

    module = REPO_ROOT / "scripts" / "lib" / "source.py"
    assert not provider_neutrality.scan_source("scripts/lib/source.py", module.read_text())

    adr = (REPO_ROOT / "docs" / "adr" / "heterogeneous-marketplace-workspaces.md").read_text()
    assert "What the drawdown does not claim" in adr
    assert "provider *knowledge*, not" in adr


def test_a3_the_credential_transport_boundary_is_named_by_the_cli() -> None:
    """An unauthenticated provider reports the boundary rather than a bare error."""
    source = LIBRARY_PY.read_text()
    assert "ProviderUnauthenticated" in source
    assert "credential handling, which is deliberately not implemented" in source


def test_the_review_evidence_file_covers_every_recorded_finding() -> None:
    """Each wave-1 finding id has a test in this file that names it."""
    body = Path(__file__).read_text()
    for finding in ("F1", "F2", "F3", "F4", "F5", "F6", "A1", "A2", "A3", "A4"):
        assert f"# {finding} " in body or f"test_{finding.lower()}_" in body, (
            f"wave-1 finding {finding} has no regression test here"
        )


def test_review_regressions_are_json_serialisable_evidence() -> None:
    """A guard that this file's own claims stay machine-readable in the notes."""
    findings = {
        "F1": "discoverable items installed through the command",
        "F2": "the Workspace write path wrote bytes the gate never admitted",
        "F3": "a projection escaped its target root through a symlink",
        "F4": "nested marker items claimed the same bytes",
        "F5": "an empty declared manifest was silently downgraded",
        "F6": "durable retention was never gated by install_rights",
        "A1": "a token-shaped value passed as a credential reference",
        "A2": "a note named an unread source in plain prose",
        "A3": "the CLI could not supply a token-scoped provider's client",
        "A4": "the drawdown claim was stronger than what it proved",
    }
    assert json.loads(json.dumps(findings)) == findings
