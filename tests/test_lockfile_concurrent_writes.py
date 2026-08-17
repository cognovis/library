#!/usr/bin/env python3
"""CL-1f36 — the global lock must survive concurrent Library writers.

During the clc-w520 deploy a scope-selecting `library agent sync --harness codex`
ran while a second Library process installed into the same
`~/.config/library/global.lock`. Every writer performed an unguarded
load-modify-save and rewrote the file through a truncating `open(path, "w")`,
so the two writers interleaved: the sync reported 3 ok / 24 failed with invalid
YAML at several lines, and the file held fragments such as a half-written
`install_timestamp` inside another entry's target list.

Two invariants are asserted here, because atomic replacement alone does not
give either one:

1. The file a reader sees always parses (no truncated or interleaved YAML).
2. Every completed install keeps its receipt (no writer saves a snapshot taken
   before another writer's save).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIBRARY_PY = SCRIPTS_DIR / "library.py"
PYTHON = sys.executable

sys.path.insert(0, str(SCRIPTS_DIR))

AGENT_COUNT = 4
STANDARD_COUNT = 3
COMPETITOR_LIMIT = 40


# ---------------------------------------------------------------------------
# Fixture project: several agents that share dependency standards
# ---------------------------------------------------------------------------


def _write_fixture_project(root: Path) -> Path:
    """Create a project whose agents share dependency standards."""
    project = root / "project"
    sources = root / "sources"
    (project / "hooks").mkdir(parents=True)
    standards_dir = sources / "standards" / "workflow"
    standards_dir.mkdir(parents=True)

    standards = []
    for index in range(STANDARD_COUNT):
        name = f"workflow/shared-standard-{index}"
        standard_file = standards_dir / f"shared-standard-{index}.md"
        standard_file.write_text(
            f"# Shared Standard {index}\n\nDependency fixture content.\n",
            encoding="utf-8",
        )
        standards.append({
            "name": name,
            "description": f"Shared dependency standard {index}",
            "source": str(standard_file),
        })

    agents = []
    for index in range(AGENT_COUNT):
        name = f"fixture-agent-{index}"
        claude_source = sources / f"{name}.md"
        codex_source = sources / f"{name}.toml"
        claude_source.write_text(
            f"---\nname: {name}\ndescription: Fixture agent {index}\n---\n\n"
            f"# Fixture Agent {index}\n",
            encoding="utf-8",
        )
        codex_source.write_text(
            f'name = "{name}"\ndescription = "Fixture agent {index}"\n',
            encoding="utf-8",
        )
        agents.append({
            "name": name,
            "description": f"Fixture agent {index}",
            "sources": {"claude": str(claude_source), "codex": str(codex_source)},
            "requires": _required_standards(standards, index),
        })

    prompts = [
        {
            "name": f"competitor-prompt-{index}",
            "description": f"Competing writer prompt {index}",
            "source": str(sources / "competitor-prompt.md"),
        }
        for index in range(COMPETITOR_LIMIT)
    ]
    (sources / "competitor-prompt.md").write_text(
        "# Competitor Prompt\n\nWritten by the competing Library process.\n",
        encoding="utf-8",
    )

    catalog = {
        "default_dirs": {
            "agents": [
                {"default": ".claude/agents/"},
                {"global": "~/.claude/agents/"},
                {"default_codex": ".codex/agents/"},
                {"global_codex": "~/.codex/agents/"},
            ],
            "standards": [
                {"default": ".agents/standards/"},
                {"global": "~/.agents/standards/"},
            ],
            "prompts": [
                {"default": ".claude/commands/"},
                {"global": "~/.claude/commands/"},
            ],
        },
        "library": {
            "agents": agents,
            "standards": standards,
            "skills": [],
            "prompts": prompts,
        },
        "marketplaces": [],
        "guardrails": [],
        "mcp_servers": [],
        "model_standards": [],
    }
    (project / "library.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False))
    return project


def _required_standards(standards: list[dict], index: int) -> list[str]:
    """Return the shared standard dependencies of one agent."""
    return [
        f"standard:{standards[index % len(standards)]['name']}",
        f"standard:{standards[(index + 1) % len(standards)]['name']}",
    ]


def _expected_agent_ids(project: Path) -> set[str]:
    """The agent roots the global lock must carry after a bulk sync."""
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    return {f"agent:{entry['name']}" for entry in catalog["library"]["agents"]}


def _expected_dependency_ids(project: Path) -> set[str]:
    """The dependency standards resolved while installing those agents.

    Dependencies resolve to their own command scope, so these land in the
    project lock rather than the global one.
    """
    catalog = yaml.safe_load((project / "library.yaml").read_text())
    return {f"standard:{entry['name']}" for entry in catalog["library"]["standards"]}


def _isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    return env


def _run_library(project: Path, home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, str(LIBRARY_PY), *args],
        capture_output=True,
        text=True,
        cwd=str(project),
        env=_isolated_env(home),
        timeout=600,
    )


COMPETING_INSTALLER = """
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, {scripts!r})

import yaml

from lib.installers.simple_file import install_simple_file

project = Path({project!r})
sentinel = Path({sentinel!r})
report = Path({report!r})
catalog = yaml.safe_load((project / "library.yaml").read_text())

installed = []
deadline = time.time() + 120
for entry in catalog["library"]["prompts"]:
    if sentinel.exists() or time.time() > deadline:
        break
    install_simple_file(
        catalog=catalog,
        primitive_name="prompt",
        name=entry["name"],
        repo_root=project,
        scope="global",
    )
    installed.append("prompt:" + entry["name"])
report.write_text(json.dumps(installed))
"""


def _start_competing_installer(
    project: Path, home: Path, sentinel: Path, report: Path
) -> subprocess.Popen:
    """Start a second Library process writing the same global lock."""
    script = COMPETING_INSTALLER.format(
        scripts=str(SCRIPTS_DIR),
        project=str(project),
        sentinel=str(sentinel),
        report=str(report),
    )
    return subprocess.Popen(
        [PYTHON, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(project),
        env=_isolated_env(home),
    )


# ---------------------------------------------------------------------------
# AC1: a multi-agent global sync keeps a parseable, complete lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attempt", range(3))
def test_multi_agent_scoped_sync_is_rejected_before_mutation(
    tmp_path: Path, attempt: int
) -> None:
    """A scope-selecting lifecycle command fails before starting concurrent work."""
    home = tmp_path / "home"
    home.mkdir()
    project = _write_fixture_project(tmp_path)
    lock_path = home / ".config" / "library" / "global.lock"

    synced = _run_library(
        project,
        home,
        "agent",
        "sync",
        "--scope",
        "global",
        "--harness",
        "codex",
        "--json",
    )

    assert synced.returncode == 1, synced.stderr or synced.stdout
    assert json.loads(synced.stdout) == {
        "status": "error",
        "message": (
            "`--scope` is not a Library option: Library manages the current Git "
            "repository only. Re-run the command without `--scope`."
        ),
        "exit_code": 1,
    }
    assert not lock_path.exists()
    assert not (project / ".library.lock").exists()


# ---------------------------------------------------------------------------
# Focused invariants of the lockfile write path
# ---------------------------------------------------------------------------


def test_failed_serialization_leaves_the_previous_lock_intact(tmp_path: Path) -> None:
    """A write that dies mid-serialization must not truncate the lock."""
    from lib import lockfile as lockfile_module

    lock_path = tmp_path / "global.lock"
    lockfile_module.save_lockfile(
        lock_path,
        {
            "schema_version": 2,
            "migration": {"prune_ack_required": False},
            "requested_roots": [],
            "receipts": [{"id": "skill:kept", "type": "skill", "name": "kept", "scope": "global"}],
            "prerequisites": [],
            "installed": [{"name": "kept", "type": "skill", "scope": "global"}],
        },
    )
    before = lock_path.read_text(encoding="utf-8")

    def _explode(*args, **kwargs):
        raise RuntimeError("serialization died mid-write")

    original_dump = yaml.dump
    yaml.dump = _explode
    try:
        with pytest.raises(RuntimeError):
            lockfile_module.save_lockfile(
                lock_path,
                {
                    "schema_version": 2,
                    "migration": {"prune_ack_required": False},
                    "requested_roots": [],
                    "receipts": [],
                    "prerequisites": [],
                    "installed": [],
                },
            )
    finally:
        yaml.dump = original_dump

    assert lock_path.read_text(encoding="utf-8") == before
    assert yaml.safe_load(lock_path.read_text(encoding="utf-8"))["receipts"][0]["id"] == "skill:kept"


CONCURRENT_MUTATOR = """
import sys
from pathlib import Path

sys.path.insert(0, {scripts!r})

from lib.lockfile import make_entry, mutate_lockfile, upsert_entry

lock_path = Path(sys.argv[1])
worker = sys.argv[2]
for index in range(int(sys.argv[3])):
    with mutate_lockfile(lock_path) as data:
        upsert_entry(
            data,
            make_entry(
                name=f"{{worker}}-{{index}}",
                primitive_type="skill",
                marketplace="local",
                source="/tmp/source",
                source_commit="local",
                cache_path="/tmp/cache/",
                install_target=f"/tmp/install/{{worker}}-{{index}}",
                checksum_sha256="0" * 64,
                scope="global",
            ),
        )
"""


def test_concurrent_lockfile_mutations_keep_every_receipt(tmp_path: Path) -> None:
    """Six Library processes mutating one lock lose nothing and corrupt nothing."""
    lock_path = tmp_path / "global.lock"
    script = CONCURRENT_MUTATOR.format(scripts=str(SCRIPTS_DIR))
    workers = 6
    per_worker = 12

    processes = [
        subprocess.Popen(
            [PYTHON, "-c", script, str(lock_path), f"worker{index}", str(per_worker)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(workers)
    ]
    for process in processes:
        out, err = process.communicate(timeout=180)
        assert process.returncode == 0, err or out

    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    receipt_ids = {receipt.get("id") for receipt in lock.get("receipts", [])}
    expected = {
        f"skill:worker{worker}-{index}"
        for worker in range(workers)
        for index in range(per_worker)
    }
    assert expected - receipt_ids == set()


def test_nested_mutation_shares_one_transaction(tmp_path: Path) -> None:
    """An installer writing inside an outer transaction must not deadlock."""
    from lib.lockfile import mutate_lockfile

    lock_path = tmp_path / "global.lock"
    finished: list[dict] = []

    def _mutate() -> None:
        with mutate_lockfile(lock_path) as outer:
            outer.setdefault("receipts", []).append({"id": "skill:outer"})
            with mutate_lockfile(lock_path) as inner:
                inner.setdefault("receipts", []).append({"id": "skill:inner"})
        finished.append(yaml.safe_load(lock_path.read_text(encoding="utf-8")))

    worker = threading.Thread(target=_mutate, daemon=True)
    worker.start()
    worker.join(timeout=30)

    assert not worker.is_alive(), "nested lockfile mutation deadlocked"
    assert finished, "nested lockfile mutation did not complete"
    ids = {receipt.get("id") for receipt in finished[0].get("receipts", [])}
    assert {"skill:outer", "skill:inner"} <= ids


def test_sync_keeps_a_root_recorded_while_it_was_reinstalling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sync must restore its own intent, not republish a whole stale snapshot.

    `reinstall_entry` re-read the lock only to write back the `requested_roots`
    it had read before the installer ran. A second Library process that recorded
    a root inside that window had it silently dropped, even though its receipt
    and its installed content survived.
    """
    from lib import sync_audit
    from lib.lockfile import make_entry, mutate_lockfile, upsert_entry

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = _write_fixture_project(tmp_path)
    lock_path = home / ".config" / "library" / "global.lock"
    catalog = yaml.safe_load((project / "library.yaml").read_text())

    synced_entry = make_entry(
        name="competitor-prompt-0",
        primitive_type="prompt",
        marketplace="local",
        source="/tmp/source",
        source_commit="local",
        cache_path="/tmp/cache/",
        install_target="/tmp/install/competitor-prompt-0",
        checksum_sha256="0" * 64,
        scope="global",
    )
    with mutate_lockfile(lock_path) as data:
        upsert_entry(data, synced_entry)

    def _install_and_race(**kwargs):
        """Stand in for the installer, with another process writing mid-install."""
        with mutate_lockfile(lock_path) as concurrent:
            upsert_entry(
                concurrent,
                make_entry(
                    name="competitor-prompt-1",
                    primitive_type="prompt",
                    marketplace="local",
                    source="/tmp/source",
                    source_commit="local",
                    cache_path="/tmp/cache/",
                    install_target="/tmp/install/competitor-prompt-1",
                    checksum_sha256="0" * 64,
                    scope="global",
                ),
            )
        return {"status": "ok", "data": {"source_commit": "local"}}

    monkeypatch.setattr(
        "lib.installers.simple_file.install_simple_file", _install_and_race
    )
    sync_audit.reinstall_entry(
        catalog,
        {"name": "competitor-prompt-0", "type": "prompt", "install_mode": "vendor"},
        project,
        "global",
        "all",
    )

    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    root_ids = {root.get("id") for root in lock.get("requested_roots", [])}
    receipt_ids = {receipt.get("id") for receipt in lock.get("receipts", [])}
    assert "prompt:competitor-prompt-1" in root_ids
    assert {"prompt:competitor-prompt-0", "prompt:competitor-prompt-1"} <= receipt_ids


def test_readers_never_observe_a_partial_lock(tmp_path: Path) -> None:
    """A reader racing a writer sees either the old or the new lock, never half."""
    from lib.lockfile import load_lockfile, make_entry, mutate_lockfile, upsert_entry

    lock_path = tmp_path / "global.lock"
    with mutate_lockfile(lock_path) as data:
        for index in range(40):
            upsert_entry(
                data,
                make_entry(
                    name=f"seed-{index}",
                    primitive_type="skill",
                    marketplace="local",
                    source="/tmp/source",
                    source_commit="local",
                    cache_path="/tmp/cache/",
                    install_target=f"/tmp/install/seed-{index}",
                    checksum_sha256="0" * 64,
                    scope="global",
                ),
            )

    stop = threading.Event()
    failures: list[Exception] = []

    def _read() -> None:
        while not stop.is_set():
            try:
                load_lockfile(lock_path)
            except Exception as exc:  # noqa: BLE001 - the assertion is "never raises"
                failures.append(exc)
                return

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    try:
        deadline = time.time() + 3
        index = 0
        while time.time() < deadline:
            with mutate_lockfile(lock_path) as data:
                upsert_entry(
                    data,
                    make_entry(
                        name=f"churn-{index}",
                        primitive_type="skill",
                        marketplace="local",
                        source="/tmp/source",
                        source_commit="local",
                        cache_path="/tmp/cache/",
                        install_target=f"/tmp/install/churn-{index}",
                        checksum_sha256="0" * 64,
                        scope="global",
                    ),
                )
            index += 1
    finally:
        stop.set()
        reader.join(timeout=30)

    assert not failures, f"reader observed a partial lock: {failures[0]}"
