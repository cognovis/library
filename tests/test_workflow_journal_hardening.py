"""Journal hardening tests for the ADR-0006 workflow runtime."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))


def _write_spike_spec(dir_path: Path) -> Path:
    """Write a spike-runtime-compatible single-leaf workflow spec.

    The spike runtime parses only a strict subset (``export const meta = {JSON}``
    + ``await agent("JSON", {JSON})``). The real cognovis-core ``bead-context-pack.js``
    is rich multi-agent JS authored for the live Workflow tool and is intentionally
    not parseable by this Python spike, so journal-hardening tests use a local spec.
    """
    spec_path = dir_path / "bead-context-pack.js"
    spec_path.write_text(
        'export const meta = {"name": "bead-context-pack"}\n'
        'await agent("gather context for the bead", '
        '{"readOnly": true, "slot": "implementation"});\n',
        encoding="utf-8",
    )
    return spec_path

from lib.workflow_runtime import (  # noqa: E402
    AgentExecutor,
    JournalSchemaError,
    JournalStore,
    ResumeContext,
    WorkflowRuntime,
)


class CountingExecutor(AgentExecutor):
    adapter_name = "claude-agent"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run(self, prompt: str, opts: dict[str, object]) -> dict[str, object]:
        self.calls.append((prompt, dict(opts)))
        return {
            "adapter": self.adapter_name,
            "prompt": prompt,
            "opts": dict(opts),
            "output": f"result-{len(self.calls)}",
        }


def _route_profiles(adapter: str = "claude-agent") -> dict[str, object]:
    return {
        "cdx-default": {
            "slots": {
                "full": {
                    "implementation": {
                        "adapter": adapter,
                        "model": "gpt-5",
                    }
                }
            }
        },
        "review": {
            "slots": {
                "full": {
                    "implementation": {
                        "adapter": adapter,
                        "model": "gpt-5",
                    }
                }
            }
        },
    }


def _run_runtime(journal_path: Path, *, route_profile: str = "cdx-default") -> tuple[dict[str, object], CountingExecutor]:
    executor = CountingExecutor()
    runtime = WorkflowRuntime(
        resume_context=ResumeContext(path=journal_path),
        executor_registry={"claude-agent": executor},
    )
    result = runtime.run(
        _write_spike_spec(journal_path.parent),
        {
            "route_profile": route_profile,
            "workflow": "full",
            "route_profiles": _route_profiles(),
        },
    )
    return result, executor


def test_journal_schema_has_version_and_identity_fields(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.json"
    spec_hash = hashlib.sha256(_write_spike_spec(tmp_path).read_bytes()).hexdigest()
    store = JournalStore(
        path=journal_path,
        spec_hash=spec_hash,
        route_profile="cdx-default",
        workflow="full",
    )

    store.put("prompt", {"slot": "implementation"}, {"result": "ok"})
    store.save()

    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    assert payload["version"] == "1"
    assert payload["spec_hash"] == spec_hash
    assert payload["route_profile"] == "cdx-default"
    assert payload["workflow"] == "full"
    assert set(payload["entries"]) == {store.key_for("prompt", {"slot": "implementation"})}


def test_journal_entry_stores_slot_and_adapter(tmp_path: Path) -> None:
    store = JournalStore(path=tmp_path / "journal.json")
    key = store.put_leaf(
        "prompt",
        {"slot": "implementation"},
        {"result": "ok"},
        slot="implementation",
        adapter="claude-agent",
    )

    entry = store.to_dict()["entries"][key]
    assert entry == {
        "slot": "implementation",
        "adapter": "claude-agent",
        "prompt_opts_hash": key,
        "result": {"result": "ok"},
        "metadata": {},
    }
    assert store.get("prompt", {"slot": "implementation"}) == {"result": "ok"}


def test_journal_atomic_write_uses_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal_path = tmp_path / "nested" / "journal.json"
    observed: list[Path] = []
    original_rename = Path.rename

    def recording_rename(self: Path, target: Path) -> Path:
        observed.append(self)
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", recording_rename)

    store = JournalStore(path=journal_path)
    store.put("prompt", {}, {"result": "ok"})
    store.save()

    assert observed == [journal_path.with_suffix(journal_path.suffix + ".tmp")]
    assert journal_path.exists()
    assert not journal_path.with_suffix(journal_path.suffix + ".tmp").exists()


def test_journal_creates_parent_dirs_on_save(tmp_path: Path) -> None:
    journal_path = tmp_path / "a" / "b" / "journal.json"
    store = JournalStore(path=journal_path)
    store.put("prompt", {}, {"result": "ok"})

    store.save()

    assert journal_path.exists()


def test_corrupt_journal_quarantines_bad_file(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.json"
    journal_path.write_text("{not json", encoding="utf-8")

    store = JournalStore.from_path(journal_path)

    assert store.entries == {}
    assert store.path == journal_path
    assert not journal_path.exists()
    assert list(tmp_path.glob("journal.corrupt*"))


def test_incompatible_journal_version_raises_schema_error(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.json"
    journal_path.write_text(
        json.dumps({"version": "0", "entries": {}}),
        encoding="utf-8",
    )

    with pytest.raises(JournalSchemaError, match="delete .*journal\\.json to reset"):
        JournalStore.from_path(journal_path)


def test_corrupt_journal_nondict_entries_raises_schema_error(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.json"
    # Write a journal where entries is a list instead of an object (malformed).
    journal_path.write_text(
        json.dumps({"version": "1", "entries": ["bad"]}),
        encoding="utf-8",
    )

    with pytest.raises(JournalSchemaError, match="malformed"):
        JournalStore.from_path(journal_path)

    # The corrupt file must be quarantined rather than silently reused.
    assert not journal_path.exists()
    assert list(tmp_path.glob("journal.corrupt*"))


def test_stale_entries_invalidated_on_spec_hash_change(tmp_path: Path) -> None:
    store = JournalStore(spec_hash="old", route_profile="cdx-default", workflow="full")
    store.put("prompt", {}, {"result": "cached"})

    invalidated = store.bind_identity("new", "cdx-default", "full")

    assert invalidated is True
    assert store.entries == {}
    assert store.spec_hash == "new"


def test_stale_entries_invalidated_on_route_profile_change(tmp_path: Path) -> None:
    store = JournalStore(spec_hash="same", route_profile="cdx-default", workflow="full")
    store.put("prompt", {}, {"result": "cached"})

    invalidated = store.bind_identity("same", "review", "full")

    assert invalidated is True
    assert store.entries == {}
    assert store.route_profile == "review"


def test_replay_uses_only_matching_entries(tmp_path: Path) -> None:
    journal_path = tmp_path / "workflow-journal.json"

    first, first_executor = _run_runtime(journal_path)
    second, second_executor = _run_runtime(journal_path)
    third, third_executor = _run_runtime(journal_path, route_profile="review")

    assert first["leaf_results"][0]["cached"] is False
    assert len(first_executor.calls) == 1
    assert second["leaf_results"][0]["cached"] is True
    assert second_executor.calls == []
    assert third["leaf_results"][0]["cached"] is False
    assert len(third_executor.calls) == 1
