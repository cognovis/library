"""The foreign-receipt fold into the v2 lock scope (routed from CL-y5z4).

`CL-y5z4` left foreign receipts in their own JSON document and routed one
decision here: fold them into `.library.lock` v2, keeping three properties its
reviewers broke the earlier shape over.

The decision this suite encodes is that the fold is a **relocation of the store
to its lock scope**, not an inlining of receipt records into the lock body. The
record shape already matches `docs/lockfile-format.md`, so nothing is
translated; what moves is ownership of *where* the records live. Inlining them
into the YAML body would put them behind `save_lockfile` and behind
`apply_post_prune_lock`'s list filtering, and each of those loses exactly one of
the three invariants below. Every test here exercises the folded entry point --
`workspace_receipt_store(lock_path)` -- so the invariants are asserted about the
thing that actually ships, not about the store the previous slice built.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.inventory import ProviderAvailability, Rights  # noqa: E402
from lib.providers.offline import ResolutionEvidence  # noqa: E402
from lib.providers.receipts import (  # noqa: E402
    RECEIPT_STORE_SCHEMA,
    ForeignReceipt,
    ProjectionStillActive,
    ReceiptStore,
    remove_named_receipt,
)
from lib.providers.retention import (  # noqa: E402
    REQUIRED_SCOPES,
    ReceiptScope,
    ReferenceIndex,
    ScopeUnreadable,
)
from lib.providers.state_files import atomic_write_text, exclusive_lock  # noqa: E402
from lib.workspace import (  # noqa: E402
    workspace_receipt_store,
    workspace_receipt_store_path,
)

NOW = "2026-08-09T09:00:00Z"
PROVIDER = "https://example.invalid/upstream"
GRANTED = Rights(
    fetch_authorization="granted",
    install_rights="granted",
    redistribution_rights="granted",
    derivative_rights="granted",
    evidence_source="upstream LICENSE, read on 2026-08-09",
)
AVAILABLE = ProviderAvailability(state="available", observed_at=NOW)


def _receipt(receipt_id: str, **overrides: Any) -> ForeignReceipt:
    base: dict[str, Any] = dict(
        id=receipt_id,
        provider_identity=PROVIDER,
        upstream_id=f"skills/{receipt_id}",
        upstream_name=receipt_id,
        collection_membership=(),
        upstream_revision=None,
        normalized_content_digest="sha256:" + "a" * 64,
        transformation_version="identity@1",
        library_type="skill",
        library_name=receipt_id,
        cache_key_digest="b" * 64,
        cache_path="/tmp/cache/object",
        install_timestamp=NOW,
        rights=GRANTED,
        executable_admission="inert",
        projection_eligibility={"project_committed": "allowed", "machine_local": "allowed"},
        provider_availability=AVAILABLE,
        verified=True,
    )
    base.update(overrides)
    return ForeignReceipt(**base)


def test_receipt_store_is_bound_to_its_lock_scope(tmp_path: Path) -> None:
    """The fold binds foreign receipts to a lock scope, not to a global path."""
    project_lock = tmp_path / "project" / ".library.lock"
    global_lock = tmp_path / "global" / "global.lock"

    project = workspace_receipt_store(project_lock)
    global_ = workspace_receipt_store(global_lock)

    assert project.path.parent == project_lock.parent
    assert global_.path.parent == global_lock.parent
    assert project.path != global_.path
    assert workspace_receipt_store_path(project_lock) == project.path
    # The lock body itself stays a lock: the fold never writes receipt records
    # into it, so `save_lockfile` keeps owning exactly what it owned before.
    assert project.path != project_lock


def test_fold_preserves_one_cross_process_lock(tmp_path: Path) -> None:
    """Invariant 1: the whole load-modify-save stays under one lock.

    Atomic replacement protects a reader from half-written JSON and does nothing
    about two writers that each loaded the file before the other saved. The
    competing writer here holds the scope lock and commits `first` while the
    forked `put` is already running. If that `put` had read the file before
    waiting, it would save a snapshot without `first` and the receipt describing
    an installed artifact would disappear.
    """
    store = workspace_receipt_store(tmp_path / ".library.lock")
    store.path.parent.mkdir(parents=True, exist_ok=True)

    with exclusive_lock(store.path):
        child = os.fork()
        if child == 0:  # pragma: no cover - the child never returns to pytest
            try:
                store.put(_receipt("second"))
            finally:
                os._exit(0)
        time.sleep(0.5)
        assert os.waitpid(child, os.WNOHANG) == (0, 0), "a second writer must wait"
        atomic_write_text(
            store.path,
            json.dumps(
                {
                    "schema": RECEIPT_STORE_SCHEMA,
                    "receipts": [_receipt("first").to_dict()],
                    "retired": [],
                }
            ),
        )

    os.waitpid(child, 0)
    assert {receipt.id for receipt in store.all()} == {"first", "second"}


def test_fold_preserves_planned_targets_before_activation(tmp_path: Path) -> None:
    """Invariant 2: a declared-but-unactivated target is still this receipt's.

    A crash between activation and finalization leaves only the plan. The folded
    store still treats those paths as claimed, so the receipt cannot be retired
    while the files it declared may exist.
    """
    store = workspace_receipt_store(tmp_path / ".library.lock")
    planned = tmp_path / "harness" / "anchor"
    planned.parent.mkdir(parents=True, exist_ok=True)
    planned.write_text("installed but never finalized\n")
    store.put(_receipt("anchor", planned_targets=(str(planned),)))

    with pytest.raises(ProjectionStillActive, match="planned"):
        remove_named_receipt(
            store,
            "anchor",
            operator="malte",
            intent="retire the baseline",
            observation=ResolutionEvidence(
                provider_identity=PROVIDER, availability=AVAILABLE, complete=True
            ),
            removed_at=NOW,
        )
    assert store.get("anchor") is not None
    assert planned.exists()


def test_fold_preserves_retirement_behind_named_removal(tmp_path: Path) -> None:
    """Invariant 3: retirement is reachable only through an explicit removal."""
    store = workspace_receipt_store(tmp_path / ".library.lock")
    store.put(_receipt("anchor"))

    with pytest.raises(ProjectionStillActive):
        store._retire(store.get("anchor"))

    assert store.get("anchor") is not None
    assert store.retired() == ()


def test_workspace_v2_adds_no_receipt_scope(tmp_path: Path) -> None:
    """Cross-catalog composition reconciles one existing lock scope, not a new one.

    `CL-uliw` routed the question here: does Workspace v2 need a new entry in
    `retention.REQUIRED_SCOPES`? It does not. Scope isolation (AC6) means a
    cross-catalog Workspace resolves entirely inside one lock scope, so a
    "workspace" scope would have no distinct location -- and `ReferenceIndex`
    refuses exactly that, because a label standing in for another scope's
    location hides every receipt that scope holds.
    """
    assert REQUIRED_SCOPES == ("project", "global")

    project = workspace_receipt_store(tmp_path / "project" / ".library.lock")
    global_ = workspace_receipt_store(tmp_path / "global" / "global.lock")
    for store in (project, global_):
        store.path.parent.mkdir(parents=True, exist_ok=True)

    index = ReferenceIndex(
        [
            ReceiptScope(name="project", store=project),
            ReceiptScope(name="global", store=global_),
        ]
    )
    assert index.scope_names == ("project", "global")

    with pytest.raises(ScopeUnreadable, match="two scopes"):
        ReferenceIndex(
            [
                ReceiptScope(name="project", store=project),
                ReceiptScope(name="global", store=global_),
                ReceiptScope(name="workspace", store=ReceiptStore(project.path)),
            ]
        )
