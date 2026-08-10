"""ADR-0011 slice 8 (`CL-st5s`): admitted bytes are published atomically.

Slice 6 left a recorded residual: the mutation gate digested an immutable
snapshot, the legacy installers resolved their own source, and the gap was
bridged by *comparison*. Comparison reports a difference after the bytes are on
disk; it does not prevent them getting there.

These tests hold the three properties that replace it:

1. the projection write path publishes the content it was handed, and the bytes
   at the final target paths are hashed after activation and compared with the
   admitted digest;
2. an activation interrupted between staging and publication leaves either the
   prior projection or the complete new one, never a partial one;
3. a target whose filesystem cannot rename atomically is refused before any
   projection byte is written, with a typed diagnostic naming the target.
"""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from typing import Mapping

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.providers.foreign_cache import normalized_content_digest  # noqa: E402
from lib.providers.wiring import (  # noqa: E402
    AdmittedContentSubstituted,
    NonAtomicProjectionTarget,
    ProjectionPublicationFailed,
    PublishedContentMismatch,
    filesystem_activation,
)

CONTENT: Mapping[str, bytes] = {
    "first.txt": b"first admitted bytes\n",
    "nested/second.txt": b"second admitted bytes\n",
    "third.txt": b"third admitted bytes\n",
}


def _projection_members(root: Path) -> dict[str, bytes]:
    """Every non-staging file beneath `root`, keyed by its relative path."""
    found: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def _failing_rename(fail_for: set[str], record: list[str]):
    """An `os.rename` that fails only for the named destinations.

    The capability probe renames a file whose name carries its own marker, so a
    fake that refused *every* rename would refuse the probe instead of the
    publication and prove the wrong thing. It also has to let the undo path
    work: an undo that cannot rename either is an untested claim.
    """
    real = os.rename

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        name = os.fsdecode(dst).rsplit("/", 1)[-1]
        record.append(name)
        if name in fail_for:
            raise OSError(errno.EIO, "injected publication failure", str(dst))
        return real(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    return rename


# -- AC1: admitted bytes are what lands, and it is asserted ------------------


def test_activation_publishes_the_admitted_bytes(tmp_path: Path) -> None:
    root = tmp_path / "projection"
    activation = filesystem_activation(
        root, admitted_digest=normalized_content_digest(CONTENT)
    )
    planned = activation.plan(CONTENT)
    created = activation.apply(CONTENT)

    assert _projection_members(root) == dict(CONTENT)
    assert sorted(target.path for target in created) == sorted(planned)


def test_a_completed_activation_leaves_no_staging_residue(tmp_path: Path) -> None:
    root = tmp_path / "projection"
    filesystem_activation(root).apply(CONTENT)

    residue = [
        path.name
        for path in root.rglob("*")
        if "library-staging" in path.name or "library-atomic-probe" in path.name
    ]
    assert residue == []


def test_content_the_gate_did_not_admit_is_refused_before_any_write(
    tmp_path: Path,
) -> None:
    """A binding to the admitted digest is what makes substitution impossible.

    Without it the writer publishes whatever it is handed and the post-activation
    check confirms it published that, which is a tautology rather than a
    guarantee.
    """
    root = tmp_path / "projection"
    activation = filesystem_activation(
        root, admitted_digest=normalized_content_digest(CONTENT)
    )
    substituted = {**CONTENT, "first.txt": b"bytes nobody admitted\n"}

    with pytest.raises(AdmittedContentSubstituted) as refusal:
        activation.apply(substituted)

    assert "first.txt" in str(refusal.value) or "admitted" in str(refusal.value)
    assert not root.exists() or _projection_members(root) == {}


def test_bytes_altered_after_staging_fail_the_post_activation_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assertion reads the final target paths, not the payload it was given.

    Hashing the mapping the caller passed in would pass while the file on disk
    said something else. This corrupts a published file between the rename and
    the check, which only a read of the real path can see.
    """
    root = tmp_path / "projection"
    root.mkdir(parents=True)
    real_rename = os.rename
    corrupted: list[str] = []

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        result = real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        name = os.fsdecode(dst).rsplit("/", 1)[-1]
        if name == "third.txt" and not corrupted:
            corrupted.append(name)
            # Every member is published by now; a concurrent writer replaces one.
            (root / "first.txt").write_bytes(b"replaced after publication\n")
        return result

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(PublishedContentMismatch) as mismatch:
        filesystem_activation(root).apply(CONTENT)

    assert "first.txt" in str(mismatch.value)


def test_a_symlinked_target_is_still_refused(tmp_path: Path) -> None:
    """Atomic publication does not get to relax containment."""
    root = tmp_path / "projection"
    root.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"untouched\n")
    (root / "first.txt").symlink_to(outside)

    with pytest.raises(Exception) as refusal:
        filesystem_activation(root).apply({"first.txt": b"redirected\n"})

    assert "symlink" in str(refusal.value)
    assert outside.read_bytes() == b"untouched\n"


# -- AC2: no partial projection ---------------------------------------------


def test_failure_before_the_first_publication_leaves_the_prior_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    prior = {
        "first.txt": b"prior first\n",
        "nested/second.txt": b"prior second\n",
        "third.txt": b"prior third\n",
    }
    for relative, payload in prior.items():
        (root / relative).write_bytes(payload)

    record: list[str] = []
    monkeypatch.setattr(
        os, "rename", _failing_rename({"first.txt", "nested", "third.txt"}, record)
    )

    with pytest.raises(ProjectionPublicationFailed):
        filesystem_activation(root).apply(CONTENT)

    assert _projection_members(root) == prior


def test_failure_partway_through_publication_restores_the_prior_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interesting injection point: some members are already published.

    A writer that renames member by member and stops is exactly the partial
    projection this bead exists to make unreachable, so the members published
    before the failure are put back.
    """
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    prior = {
        "first.txt": b"prior first\n",
        "nested/second.txt": b"prior second\n",
        "third.txt": b"prior third\n",
    }
    for relative, payload in prior.items():
        (root / relative).write_bytes(payload)

    record: list[str] = []
    monkeypatch.setattr(os, "rename", _failing_rename({"third.txt"}, record))

    with pytest.raises(ProjectionPublicationFailed) as failure:
        filesystem_activation(root).apply(CONTENT)

    assert "third.txt" in str(failure.value)
    assert _projection_members(root) == prior


def test_an_interrupted_activation_removes_members_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no prior projection, the prior state is "nothing"."""
    root = tmp_path / "projection"
    record: list[str] = []
    monkeypatch.setattr(os, "rename", _failing_rename({"third.txt"}, record))

    with pytest.raises(ProjectionPublicationFailed):
        filesystem_activation(root).apply(CONTENT)

    assert _projection_members(root) == {}


def test_no_target_ever_holds_a_partially_written_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every observed state of a target is a complete version of it.

    The publication phase is watched: at every rename, every target that exists
    holds either its prior bytes or its admitted bytes, never a prefix.
    """
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    prior = {relative: b"prior\n" for relative in CONTENT}
    for relative, payload in prior.items():
        (root / relative).write_bytes(payload)

    observed: list[dict[str, bytes]] = []
    real_rename = os.rename

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        observed.append(_projection_members(root))
        result = real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        observed.append(_projection_members(root))
        return result

    monkeypatch.setattr(os, "rename", rename)
    filesystem_activation(root).apply(CONTENT)

    assert observed, "the publication phase renamed at least once"
    for snapshot in observed:
        for relative, payload in snapshot.items():
            if any(
                marker in relative
                for marker in ("library-staging", "library-atomic-probe", "library-undo")
            ):
                continue
            assert payload in (prior[relative], CONTENT[relative]), (
                f"{relative} was observed holding neither its prior nor its "
                "admitted bytes"
            )


# -- AC3: a non-atomic target is refused ------------------------------------


def test_a_target_without_atomic_rename_is_refused_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projection"

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        raise OSError(errno.EXDEV, "Cross-device link", str(dst))

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(NonAtomicProjectionTarget) as refusal:
        filesystem_activation(root).apply(CONTENT)

    message = str(refusal.value)
    assert str(root) in message
    assert "Cross-device link" in message or "EXDEV" in message
    assert _projection_members(root) == {}


def test_a_non_atomic_target_is_not_written_by_a_copy_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`CL-m6cc`: approximating atomicity is the defect, so refusal is the only
    fallback. Nothing beneath the root may exist after the refusal."""
    root = tmp_path / "projection"

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        raise OSError(errno.ENOSYS, "rename not supported", str(dst))

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(NonAtomicProjectionTarget):
        filesystem_activation(root).apply(CONTENT)

    assert [path for path in root.rglob("*") if path.is_file()] == []


# -- wave-1 review findings, held as regression tests ------------------------
#
# The mandated co-reviewer could not run, so every counterexample the reviewer
# that did run executed is kept here rather than read once and discarded.


def test_f3_a_refused_target_keeps_no_directory_the_activation_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave-1 `CL-st5s-F3`: the refusal must precede *every* mutation.

    The reviewer forced each probe rename to `EXDEV` and found the projection
    root and its `nested/` subdirectory left behind: the payload bytes were
    refused, but the layout had already been built. An activation that refuses
    leaves the filesystem as it found it, directories included.
    """
    root = tmp_path / "projection"

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        raise OSError(errno.EXDEV, "Cross-device link", str(dst))

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(NonAtomicProjectionTarget):
        filesystem_activation(root).apply(CONTENT)

    assert not root.exists(), "an absent target root stays absent after a refusal"
    assert list(tmp_path.iterdir()) == []


def test_f3_a_refusal_keeps_directories_that_already_existed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The undo removes what it created, and nothing else."""
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    (root / "unrelated.txt").write_bytes(b"someone else's file\n")

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        raise OSError(errno.EXDEV, "Cross-device link", str(dst))

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(NonAtomicProjectionTarget):
        filesystem_activation(root).apply(CONTENT)

    assert (root / "nested").is_dir()
    assert (root / "unrelated.txt").read_bytes() == b"someone else's file\n"


def test_f2_an_interruption_is_not_a_gentler_failure_than_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave-1 `CL-st5s-F2`: `KeyboardInterrupt` left a mixed projection.

    The publication loop restored only on `OSError`, so an interruption walked
    out through `finally` with two members published and one not.
    """
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    prior = {
        "first.txt": b"prior first\n",
        "nested/second.txt": b"prior second\n",
        "third.txt": b"prior third\n",
    }
    for relative, payload in prior.items():
        (root / relative).write_bytes(payload)

    real_rename = os.rename

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        if os.fsdecode(dst).rsplit("/", 1)[-1] == "third.txt":
            raise KeyboardInterrupt("injected interruption")
        return real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(KeyboardInterrupt):
        filesystem_activation(root).apply(CONTENT)

    assert _projection_members(root) == prior


def test_f2_a_failed_undo_adds_nothing_to_the_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave-1 `CL-st5s-F2`, second half: undo material stayed in the tree.

    When both the publication rename and the undo rename fail, the target is
    honestly reported as untrusted -- but `.<name>.library-undo.<token>` files
    were left inside the projection, where any recursive reader counts them as
    content.
    """
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    prior = {
        "first.txt": b"prior first\n",
        "nested/second.txt": b"prior second\n",
        "third.txt": b"prior third\n",
    }
    for relative, payload in prior.items():
        (root / relative).write_bytes(payload)

    real_rename = os.rename

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        name = os.fsdecode(dst).rsplit("/", 1)[-1]
        source = os.fsdecode(src).rsplit("/", 1)[-1]
        if name == "third.txt" or "library-undo" in source:
            raise OSError(errno.EIO, "injected failure", str(dst))
        return real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(ProjectionPublicationFailed) as failure:
        filesystem_activation(root).apply(CONTENT)

    assert failure.value.unrestored, "a failed undo names what it could not restore"
    leftovers = [
        path.name
        for path in root.rglob("*")
        if "library-undo" in path.name or "library-staging" in path.name
    ]
    assert leftovers == []


# -- wave-2 review findings, held as regression tests ------------------------


def test_w2f2_an_interruption_during_staging_leaves_no_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave-2 `CL-st5s-W2-F2`: the artifact whose creation was interrupted.

    The reviewer raised `KeyboardInterrupt` from the `fsync` inside
    `_create_beneath`. The member had not been registered yet, so the cleanup —
    which iterated the members it had successfully staged — never saw the file,
    and it survived along with the root that had just been created for it.
    """
    root = tmp_path / "projection"
    real_fsync = os.fsync
    raised: list[int] = []

    def fsync(fd):
        if not raised:
            raised.append(fd)
            raise KeyboardInterrupt("injected interruption during staging")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    with pytest.raises(KeyboardInterrupt):
        filesystem_activation(root).apply(CONTENT)

    assert not root.exists(), "the root created for an interrupted staging is removed"
    assert list(tmp_path.iterdir()) == []


def test_w2f2_an_interruption_during_the_probe_leaves_no_probe_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave-2 `CL-st5s-W2-F2`: the probe cleaned up only on `OSError`.

    `SystemExit` from the probe rename left `.library-atomic-probe.<token>` and,
    because that file made the directory non-empty, the created root as well.
    """
    root = tmp_path / "projection"

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        raise SystemExit("injected interruption during the capability probe")

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(SystemExit):
        filesystem_activation(root).apply(CONTENT)

    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


def test_w2f2_the_undo_material_exists_before_the_first_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restoration creates nothing, so it cannot fail for a new reason.

    Wave 2 showed a partially failed undo leaving prior/new/prior across three
    targets. The undo can still fail if the filesystem refuses a rename it just
    proved it could do, but it no longer *writes* during recovery: every undo
    file is in place before the first publication rename, which is why a failure
    to create one refuses the activation instead of surfacing halfway through
    putting it back.
    """
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    for relative in CONTENT:
        (root / relative).write_bytes(b"prior\n")

    seen: list[list[str]] = []
    real_rename = os.rename

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        name = os.fsdecode(dst).rsplit("/", 1)[-1]
        if name in CONTENT or name == "first.txt":
            seen.append(sorted(path.name for path in root.rglob("*.library-undo.*")))
        return real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "rename", rename)
    filesystem_activation(root).apply(CONTENT)

    assert seen, "the publication phase ran"
    assert len(seen[0]) == len(CONTENT), (
        "every member's undo material exists before the first publication rename"
    )
    assert list(root.rglob("*.library-undo.*")) == []


def test_w2f2_a_failed_undo_names_every_target_it_could_not_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The remaining honest limit, asserted rather than described.

    A filesystem that refuses a same-directory rename during recovery leaves that
    target holding the new bytes while its siblings are back on the old ones. The
    activation does not report that as success: it fails, and it enumerates every
    target it could not put back, so an operator knows exactly which paths are
    untrusted.
    """
    root = tmp_path / "projection"
    (root / "nested").mkdir(parents=True)
    prior = {relative: b"prior\n" for relative in CONTENT}
    for relative, payload in prior.items():
        (root / relative).write_bytes(payload)

    real_rename = os.rename

    def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        name = os.fsdecode(dst).rsplit("/", 1)[-1]
        source = os.fsdecode(src).rsplit("/", 1)[-1]
        if name == "third.txt":
            raise OSError(errno.EIO, "injected publication failure", str(dst))
        if "library-undo" in source and name == "second.txt":
            raise OSError(errno.EIO, "injected undo failure", str(dst))
        return real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(ProjectionPublicationFailed) as failure:
        filesystem_activation(root).apply(CONTENT)

    unrestored = failure.value.unrestored
    assert [path for path in unrestored if path.endswith("nested/second.txt")], unrestored
    assert "must be treated as untrusted" in str(failure.value)
    # The targets it could restore are back on their prior bytes, and nothing
    # extra is left in the tree.
    members = _projection_members(root)
    assert members["first.txt"] == prior["first.txt"]
    assert members["third.txt"] == prior["third.txt"]
    assert [name for name in members if "library-" in name] == []
