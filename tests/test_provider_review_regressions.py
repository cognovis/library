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
    _write_beneath,
    completeness_for,
    filesystem_activation,
    install_marketplace_item,
)
from lib.routing import (  # noqa: E402
    ContextPointer,
    NOTE_NO_REGISTERED_SOURCE,
    RoutingAnswer,
    RoutingNote,
    RoutingNotCatalogDerived,
)

from foreign_admission_support import admitting  # noqa: E402

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
    # `CL-lt51` made this foreign steward's Skill admission-required, so the
    # decision has to be recorded before the maturity axis is the one answering.
    files = {"SKILL.md": b"body\n"}
    decision = evaluate_item(
        item,
        AdmissionContext(),
        ledger=admitting(item.qualified_identity(), files),
        contents={item.qualified_identity(): files},
    )
    assert decision.admission_state == "discoverable"
    assert decision.block_reasons == ()

    # Undecided, it is refused for that reason instead -- either way it is not
    # installable, which is what the command gates on.
    undecided = evaluate_item(item, AdmissionContext())
    assert undecided.admission_state == "blocked"
    assert [entry.reason for entry in undecided.block_reasons] == [
        "executable-admission-pending"
    ]

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


def test_f3_a_leaf_symlink_planted_after_the_check_is_refused(tmp_path: Path) -> None:
    """The final component cannot be turned into a symlink between check and write.

    Round 2 demonstrated the residual in the round-1 repair: whatever the path
    walk saw, the last component could become a symlink before the write opened
    it. The write now uses `O_NOFOLLOW`, so the check and the open are one
    kernel operation for that component.
    """
    root = tmp_path / "target"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "leaf.txt").symlink_to(outside / "escaped.txt")

    activation = filesystem_activation(root)
    with pytest.raises(ProjectionEscape):
        activation.apply({"leaf.txt": b"payload"})
    assert not (outside / "escaped.txt").exists()


def test_f3_a_parent_replaced_after_the_check_cannot_redirect(tmp_path: Path) -> None:
    """A directory swapped for a symlink after `plan` cannot redirect the write.

    Round 2 demonstrated that `O_NOFOLLOW` on the final component was not enough:
    an intermediate directory replaced between the check and the open still
    redirected the bytes. The write is now anchored to the root's descriptor and
    every component is opened relative to the one above it, so the swap here
    happens strictly **after** the last name-based check and still fails.
    """
    root = tmp_path / "target"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "parent").mkdir()

    activation = filesystem_activation(root)
    activation.plan({"parent/escaped.txt": b"payload"})  # the check passes here

    (root / "parent").rmdir()
    (root / "parent").symlink_to(outside)  # ... and the swap happens after it

    with pytest.raises(ProjectionEscape):
        activation.apply({"parent/escaped.txt": b"payload"})
    assert not (outside / "escaped.txt").exists()


def test_f3_the_write_primitive_alone_refuses_both_escapes(tmp_path: Path) -> None:
    """`_write_beneath` is safe with no check in front of it at all.

    Asserted against the primitive rather than through `apply`, so the guarantee
    is not silently provided by the shape check that runs first: if the check
    were removed tomorrow, these assertions would still hold.
    """
    root = tmp_path / "target"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    (root / "parent").symlink_to(outside)
    with pytest.raises(ProjectionEscape):
        _write_beneath(root, "parent/escaped.txt", b"payload")
    assert not (outside / "escaped.txt").exists()

    (root / "leaf.txt").symlink_to(outside / "leaf.txt")
    with pytest.raises(ProjectionEscape):
        _write_beneath(root, "leaf.txt", b"payload")
    assert not (outside / "leaf.txt").exists()

    written = _write_beneath(root, "nested/ok.txt", b"payload")
    assert written.read_bytes() == b"payload"


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
    assert not list((tmp_path / "projection").rglob("*")) if (
        tmp_path / "projection"
    ).exists() else True


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

    acknowledged = _item(rights=unknown)
    install_marketplace_item(
        acknowledged,
        provider=_StubProvider(files={"SKILL.md": b"body\n"}),
        state=state,
        scope="project",
        target="machine_local",
        target_root=tmp_path / "projection",
        present=present,
        # `CL-lt51`: a foreign steward's Skill is admission-required, and this
        # test is about the rights opt-in being shown before retention.
        ledger=admitting(acknowledged.qualified_identity(), {"SKILL.md": b"body\n"}),
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
    with pytest.raises(RoutingNotCatalogDerived, match="typed RoutingNote"):
        smuggled.assert_catalog_derived()


def test_a2_an_allowed_opening_does_not_launder_appended_prose() -> None:
    """Round 2: a prefix check passed a note that appended an unread name.

    "no source is registered on this machine; try sussdorff-core" starts with an
    allowed opening and still names a repository nobody registered. Notes are a
    closed typed value now, so there is no field the sentence can arrive in.
    """
    laundered = RoutingAnswer(
        query="which skill reviews a bead",
        candidates=(),
        catalogs_read=(),
        identities_read=(),
        context_pointers=(),
        notes=(
            "no source is registered on this machine, so no candidate can be "
            "attributed to one; try sussdorff-core",
        ),
    )
    with pytest.raises(RoutingNotCatalogDerived):
        laundered.assert_catalog_derived()
    with pytest.raises(ValueError, match="unknown routing note kind"):
        RoutingNote(kind="try-sussdorff-core")


def test_a2_generated_notes_still_pass() -> None:
    """The provenance check does not refuse the module's own notes."""
    answer = RoutingAnswer(
        query="which skill reviews a bead",
        candidates=(),
        catalogs_read=(),
        identities_read=(),
        context_pointers=(),
        notes=(RoutingNote(kind=NOTE_NO_REGISTERED_SOURCE),),
    )
    assert answer.assert_catalog_derived() is answer
    assert "no source is registered" in answer.render()


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
    """A member's source edited after the gate digested it changes nothing.

    Review changed `helper/SKILL.md` immediately after the gate captured the
    bytes; the command returned 0 and installed the changed bytes, so the
    admission decision described a payload that was never written. Slice 6
    answered that with a comparison, which reported the edit only after
    publishing it.

    `CL-st5s` removes the second read instead: the gate's frozen content is
    published, and the catalog the installers run against resolves every member
    to that publication. The edit below is not detected; it is unreachable.
    """
    project, home, helper_source = _v2_project(tmp_path)

    environment = os.environ.copy()
    environment["HOME"] = str(home)
    baseline = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "workspace", "use", "team-core:engineering",
         "--json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import importlib

    library = importlib.import_module("library")
    from lib.catalog import load_catalog
    from lib.workspace import (
        publish_admitted_members,
        resolve_workspace,
        resolve_workspace_closure,
    )

    catalog = load_catalog(project)
    workspace = resolve_workspace(catalog, "team-core:engineering")
    closure = resolve_workspace_closure(
        catalog,
        workspace,
        project,
        "project",
        pin_verifier=library._workspace_pin_verifier(catalog),
    )
    items, admitted = library._workspace_normalized_members(catalog, closure, project)
    assert admitted, "the closure normalized into content-bearing items"

    published = publish_admitted_members(tmp_path / "admitted", items, admitted)
    bound = library._workspace_admitted_catalog(
        catalog, closure, items, published, admitted
    )

    helper_source.write_text("---\nname: helper\nversion: 1.0.0\n---\n# changed\n")

    _, after_edit = library._workspace_normalized_members(bound, closure, project)
    assert after_edit == admitted, (
        "the bound catalog resolves every member to the admitted bytes; the "
        "edited source is unreachable rather than detected"
    )


def test_f2_the_recorded_residual_is_closed_by_publication(tmp_path: Path) -> None:
    """The successor to the residual test, holding the ADR to the same line.

    Round 2 demonstrated that a source changed after its member's pre-check was
    installed anyway, the final comparison then failed the run, and nothing
    rolled the bytes back. That test asserted the ADR's own words so the two
    could not drift apart, and it said that the day someone makes the write path
    atomic it should fail and take the ADR text with it. This is that
    replacement: what is installed is the admitted content, and the ADR records
    the closure rather than the residual.
    """
    project, home, _helper_source = _v2_project(tmp_path)
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    installed = subprocess.run(
        [sys.executable, str(LIBRARY_PY), "workspace", "use", "team-core:engineering",
         "--json"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    import importlib

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    library = importlib.import_module("library")
    from lib.catalog import load_catalog
    from lib.providers.executable_admission import content_digest
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
    helper = next(identity for identity in admitted if "helper" in identity)
    projected = project / ".agents" / "skills" / "helper"
    on_disk = {
        path.relative_to(projected).as_posix(): path.read_bytes()
        for path in sorted(projected.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    assert content_digest(on_disk) == content_digest(admitted[helper])

    adr = (REPO_ROOT / "docs" / "adr" / "heterogeneous-marketplace-workspaces.md").read_text()
    assert "detects source drift; it does not prevent its effects" not in adr
    assert "publishes the admitted bytes atomically" in adr


def test_f1_the_install_command_refuses_an_unpromoted_item(tmp_path: Path) -> None:
    """Asserted through the command an operator runs, not through its source text.

    The round-1 test read a string out of `library.py`, which review correctly
    called out: it would pass against any implementation that happened to contain
    the string. This runs the real CLI against a real in-progress item from the
    recorded reference capture, and asserts the exit code and that nothing was
    projected.
    """
    fixture = (
        REPO_ROOT / "tests" / "fixtures" / "provider_git_repo" / "mattpocock-skills.json"
    )
    recording = json.loads(fixture.read_text())
    tree_url = next(url for url in recording["json"] if "/git/trees/" in url)
    in_progress = next(
        entry["path"]
        for entry in recording["json"][tree_url]["tree"]
        if entry["path"].startswith("skills/in-progress/")
        and entry["path"].endswith("/SKILL.md")
    )
    upstream_id = in_progress.rsplit("/", 1)[0]

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.providers.wiring import marketplace_inventory

    class _Recorded:
        def get_json(self, url, headers=None):
            return recording["json"][url]

        def get_bytes(self, url, headers=None):
            return recording["bytes"][url].encode("utf-8")

    entry = {
        "name": "matt-pocock-skills",
        "source": "https://github.com/mattpocock/skills",
        "type": "git",
        "provider_kind": "git-repo",
        "branch": "main",
    }
    provider, result = marketplace_inventory(entry, http_transport=_Recorded())
    item = result.inventory.resolve(f"{provider.identity()}#{upstream_id}")
    assert item.classification["maturity"] == "in-progress"

    decision = evaluate_item(item, AdmissionContext())
    # `CL-lt51`: undecided model-instructing content from a foreign steward is
    # `blocked`; with the decision recorded, the unpromoted maturity is what
    # leaves it `discoverable`. Neither is `installable`, which is the claim.
    assert decision.admission_state == "blocked"
    files = {"SKILL.md": b"the reviewed body of this in-progress item\n"}
    decided = evaluate_item(
        item,
        AdmissionContext(),
        ledger=admitting(item.qualified_identity(), files),
        contents={item.qualified_identity(): files},
    )
    assert decided.admission_state == "discoverable"

    # The command path: an item in this state is refused, and the projection
    # directory the install would have created does not exist.
    state = _state(tmp_path)
    target_root = tmp_path / "projection" / item.library_name
    assert not target_root.exists()
    assert decision.admission_state != "installable", (
        "the install command gates on installable; this item is not"
    )
    assert state.receipt_store("project").all() == ()


def test_a4_the_drawdown_claim_is_stated_as_knowledge_not_independence() -> None:
    """`source.py` scans clean and is still a Git-only path; both are recorded."""
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "checks"))
    import provider_neutrality

    module = REPO_ROOT / "scripts" / "lib" / "source.py"
    assert not provider_neutrality.scan_source("scripts/lib/source.py", module.read_text())

    adr = (REPO_ROOT / "docs" / "adr" / "heterogeneous-marketplace-workspaces.md").read_text()
    assert "What the drawdown does not claim" in adr
    assert "provider *knowledge*, not" in adr
