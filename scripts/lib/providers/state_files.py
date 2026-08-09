"""Cross-process serialization and atomic writes for durable state files.

Two small facts drove this module out of its callers.

**Atomic replacement is not an atomic transaction.** `os.replace` makes a write
indivisible for readers; it does nothing for the read that decided what to
write. Every store here follows load-modify-save, and review demonstrated the
consequence twice: two concurrent first-use pins each decided they were the
first, and two concurrent receipt writes each saved a snapshot taken before the
other, so one install's receipt vanished while its content stayed installed.

**A `finally` block does not run after a hard kill.** Anything staged by a
process that was killed has to be identifiable as abandoned by a later process,
which means the writer's identity has to be part of what it leaves behind.

Locks are advisory `flock` locks on a sidecar file. They serialize cooperating
Library processes; they are not a defense against a process that ignores them.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import os
import uuid
from pathlib import Path
from typing import Iterator

#: Suffix for the sidecar lock file guarding one state file.
LOCK_SUFFIX = ".lock"


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Serialize a whole read-modify-write across processes on one state file.

    The lock is taken on a sidecar beside `path` rather than on `path` itself,
    because the state file is replaced by rename on every write and a lock held
    on the replaced inode would protect nothing after the first save.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}{LOCK_SUFFIX}")
    handle = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def scoped_lock_path(path: Path, scope: str) -> Path:
    """A per-scope lock file beside one state file.

    Used to serialize everything that happens for a single item identity -- the
    pin decision, the materialization, the receipt, and the projection -- rather
    than only the pin write. Review paused an install after it verified the pin,
    re-pinned the identity to different bytes, and let the install finish: the
    durable pin and the installed content ended up describing different content.

    The scope is hashed because an identity is opaque provider-native text and
    may contain anything, including separators.
    """
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]
    return Path(path).with_name(f"{Path(path).name}.{digest}{LOCK_SUFFIX}")


def atomic_write_text(path: Path, text: str) -> Path:
    """Replace one file's contents indivisibly for readers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f"{path.name}.{uuid.uuid4().hex}.staged")
    try:
        staged.write_text(text, encoding="utf-8")
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)
    return path


def process_is_alive(pid: int) -> bool:
    """Whether a process id still exists.

    `EPERM` means the process exists and belongs to somebody else, which is
    still alive. Only `ESRCH` proves it is gone, and only that answer is safe to
    act on when the action is deleting the process's working files.
    """
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def owner_pid(name: str) -> int | None:
    """The writing process id encoded in a `<pid>-<unique>` entry name."""
    head, separator, _ = name.partition("-")
    if not separator or not head.isdigit():
        return None
    return int(head)


__all__ = [
    "LOCK_SUFFIX",
    "atomic_write_text",
    "exclusive_lock",
    "owner_pid",
    "process_is_alive",
    "scoped_lock_path",
]
