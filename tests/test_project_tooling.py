#!/usr/bin/env python3
"""
test_project_tooling.py — Tests for project_tooling: schema in library.yaml

Bead: CL-3fh
Tests:
  1.  project_tooling section present in library.yaml is accepted by validator
  2.  project_tooling_entry requires name
  3.  project_tooling_entry requires description
  4.  project_tooling_entry requires target_kind
  5.  project_tooling_entry requires target_path
  6.  target_kind enum accepts only valid values; rejects unknown
  7.  sync_strategy enum accepts only valid values; rejects unknown
  8.  conflict_policy enum accepts only valid values; rejects unknown
  9.  conditions language (dir_exists / file_exists / command_available / env_set) accepted
  10. fields section (json_field_enforce) validates correctly
  11. Full beads-prime example validates cleanly
  12. Actual library.yaml with project_tooling section passes validator
  13. sync_project_tooling.py: file target sync works (integration test, temp dirs)
  14. sync_project_tooling.py: json_field_enforce ensure/remove works
  15. sync_project_tooling.py: running sync twice is idempotent

Run with:
    python3 -m pytest tests/test_project_tooling.py -v
  or:
    python3 tests/test_project_tooling.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    print("SKIP: PyYAML not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(0)

try:
    import jsonschema
    from jsonschema import validate, ValidationError
except ImportError:
    print("SKIP: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"
LIBRARY_PATH = REPO_ROOT / "library.yaml"
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_project_tooling.py"


def load_schema() -> dict:
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def minimal_library(extra: dict | None = None) -> dict:
    """Return a minimal valid library.yaml structure, optionally merged with extra keys."""
    base = {
        "default_dirs": {
            "skills": [{"default": ".claude/skills/"}],
        },
        "library": {
            "skills": [],
            "agents": [],
            "prompts": [],
        },
        "marketplaces": [],
    }
    if extra:
        base.update(extra)
    return base


def assert_valid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        msgs = "\n".join(f"  [{'/'.join(str(p) for p in e.absolute_path)}] {e.message}" for e in errors)
        raise AssertionError(f"Expected VALID for '{label}' but got errors:\n{msgs}")


def assert_invalid(data: dict, schema: dict, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    if not errors:
        raise AssertionError(f"Expected INVALID for '{label}' but schema accepted it")


def minimal_tooling_entry(**overrides) -> dict:
    """Return a minimal valid project_tooling entry."""
    entry = {
        "name": "test-entry",
        "description": "A test tooling entry",
        "target_kind": "file",
        "target_path": ".beads/PRIME.md",
    }
    entry.update(overrides)
    return entry


# ---------------------------------------------------------------------------
# Test cases — Schema validation
# ---------------------------------------------------------------------------

def test_project_tooling_section_accepted():
    """A minimal project_tooling entry is accepted by schema."""
    schema = load_schema()
    data = minimal_library({
        "project_tooling": [
            minimal_tooling_entry()
        ]
    })
    assert_valid(data, schema, "project_tooling with minimal valid entry")
    print("PASS test_project_tooling_section_accepted")


def test_project_tooling_requires_name():
    """project_tooling_entry without name is rejected."""
    schema = load_schema()
    entry = minimal_tooling_entry()
    del entry["name"]
    data = minimal_library({"project_tooling": [entry]})
    assert_invalid(data, schema, "project_tooling_entry missing name")
    print("PASS test_project_tooling_requires_name")


def test_project_tooling_requires_description():
    """project_tooling_entry without description is rejected."""
    schema = load_schema()
    entry = minimal_tooling_entry()
    del entry["description"]
    data = minimal_library({"project_tooling": [entry]})
    assert_invalid(data, schema, "project_tooling_entry missing description")
    print("PASS test_project_tooling_requires_description")


def test_project_tooling_requires_target_kind():
    """project_tooling_entry without target_kind is rejected."""
    schema = load_schema()
    entry = minimal_tooling_entry()
    del entry["target_kind"]
    data = minimal_library({"project_tooling": [entry]})
    assert_invalid(data, schema, "project_tooling_entry missing target_kind")
    print("PASS test_project_tooling_requires_target_kind")


def test_project_tooling_requires_target_path():
    """project_tooling_entry without target_path is rejected."""
    schema = load_schema()
    entry = minimal_tooling_entry()
    del entry["target_path"]
    data = minimal_library({"project_tooling": [entry]})
    assert_invalid(data, schema, "project_tooling_entry missing target_path")
    print("PASS test_project_tooling_requires_target_path")


def test_target_kind_enum():
    """target_kind accepts only valid values; unknown is rejected."""
    schema = load_schema()

    valid_kinds = ("file", "file_section", "git_hook", "gitignore_patch", "json_field_enforce")
    for kind in valid_kinds:
        data = minimal_library({
            "project_tooling": [minimal_tooling_entry(target_kind=kind)]
        })
        assert_valid(data, schema, f"target_kind={kind}")

    data_invalid = minimal_library({
        "project_tooling": [minimal_tooling_entry(target_kind="unknown_kind")]
    })
    assert_invalid(data_invalid, schema, "target_kind=unknown_kind (invalid)")
    print("PASS test_target_kind_enum")


def test_sync_strategy_enum():
    """sync_strategy accepts only valid values; unknown is rejected."""
    schema = load_schema()

    valid_strategies = (
        "overwrite_if_source_newer",
        "overwrite_always",
        "append_if_missing",
        "replace_section",
        "repair_fields",
    )
    for strategy in valid_strategies:
        data = minimal_library({
            "project_tooling": [minimal_tooling_entry(sync_strategy=strategy)]
        })
        assert_valid(data, schema, f"sync_strategy={strategy}")

    data_invalid = minimal_library({
        "project_tooling": [minimal_tooling_entry(sync_strategy="clobber_always")]
    })
    assert_invalid(data_invalid, schema, "sync_strategy=clobber_always (invalid)")
    print("PASS test_sync_strategy_enum")


def test_conflict_policy_enum():
    """conflict_policy accepts only valid values; unknown is rejected."""
    schema = load_schema()

    valid_policies = ("canonical_wins", "user_wins", "warn_only")
    for policy in valid_policies:
        data = minimal_library({
            "project_tooling": [minimal_tooling_entry(conflict_policy=policy)]
        })
        assert_valid(data, schema, f"conflict_policy={policy}")

    data_invalid = minimal_library({
        "project_tooling": [minimal_tooling_entry(conflict_policy="merge_it")]
    })
    assert_invalid(data_invalid, schema, "conflict_policy=merge_it (invalid)")
    print("PASS test_conflict_policy_enum")


def test_conditions_language():
    """conditions array with dir_exists/file_exists/command_available/env_set accepted."""
    schema = load_schema()
    data = minimal_library({
        "project_tooling": [
            minimal_tooling_entry(conditions=[
                {"dir_exists": ".beads"},
                {"file_exists": ".beads/metadata.json"},
                {"command_available": "bd"},
                {"env_set": "COGNOVIS_LIBRARY"},
            ])
        ]
    })
    assert_valid(data, schema, "conditions with all valid condition types")
    print("PASS test_conditions_language")


def test_json_field_enforce_fields():
    """fields section for json_field_enforce validates correctly."""
    schema = load_schema()

    # With ensure and remove
    data = minimal_library({
        "project_tooling": [
            minimal_tooling_entry(
                target_kind="json_field_enforce",
                fields={
                    "ensure": {"dolt_mode": "server"},
                    "remove": ["database", "backend"],
                },
            )
        ]
    })
    assert_valid(data, schema, "json_field_enforce with fields.ensure and fields.remove")

    # Invalid: unknown property inside fields
    data_invalid = minimal_library({
        "project_tooling": [
            minimal_tooling_entry(
                target_kind="json_field_enforce",
                fields={
                    "ensure": {"dolt_mode": "server"},
                    "unknown_prop": "bad",
                },
            )
        ]
    })
    assert_invalid(data_invalid, schema, "fields with unknown property (invalid)")
    print("PASS test_json_field_enforce_fields")


def test_full_beads_prime_example():
    """The full beads-prime entry from the bead description validates cleanly."""
    schema = load_schema()
    data = minimal_library({
        "project_tooling": [
            {
                "name": "beads-prime",
                "description": (
                    "bd workflow primer — auto-synced from cognovis-library at SessionStart. "
                    "bd prime emits its content. Fleet policy, not per-project customization."
                ),
                "target_kind": "file",
                "target_path": ".beads/PRIME.md",
                "source": "prime/PRIME.md",
                "conditions": [
                    {"dir_exists": ".beads"},
                ],
                "sync_strategy": "overwrite_if_source_newer",
                "conflict_policy": "canonical_wins",
                "consumed_by": {
                    "tool": "bd",
                    "command": "bd prime",
                },
                "tags": ["beads", "fleet-policy"],
            }
        ]
    })
    assert_valid(data, schema, "full beads-prime example")
    print("PASS test_full_beads_prime_example")


def test_library_yaml_has_project_tooling():
    """Actual library.yaml (with project_tooling) passes validator."""
    schema = load_schema()
    with LIBRARY_PATH.open() as f:
        data = yaml.safe_load(f)
    assert_valid(data, schema, "library.yaml on disk (with project_tooling)")
    print("PASS test_library_yaml_has_project_tooling")


# ---------------------------------------------------------------------------
# Test cases — Runtime (integration tests using temp dirs)
# ---------------------------------------------------------------------------

def _import_sync_script():
    """Dynamically import sync_project_tooling.py for integration tests."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_project_tooling", SYNC_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sync_runtime_file_target():
    """sync_project_tooling.py: file target with overwrite_if_source_newer works."""
    sync = _import_sync_script()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        lib_root = tmp / "library"
        project_root = tmp / "project"
        lib_root.mkdir()
        project_root.mkdir()

        # Create source file in library
        source_content = "# Fleet PRIME\nHello from fleet."
        source_file = lib_root / "prime" / "PRIME.md"
        source_file.parent.mkdir(parents=True)
        source_file.write_text(source_content)

        # Create .beads dir in project (condition: dir_exists .beads)
        (project_root / ".beads").mkdir()

        entries = [
            {
                "name": "beads-prime",
                "description": "Test prime entry",
                "target_kind": "file",
                "target_path": ".beads/PRIME.md",
                "source": "prime/PRIME.md",
                "conditions": [{"dir_exists": ".beads"}],
                "sync_strategy": "overwrite_if_source_newer",
                "conflict_policy": "canonical_wins",
            }
        ]

        result = sync.sync_entries(entries, library_root=lib_root, project_root=project_root)
        assert result["synced"] >= 1, f"Expected at least 1 synced entry, got: {result}"

        target_file = project_root / ".beads" / "PRIME.md"
        assert target_file.exists(), "Target file was not created"
        assert target_file.read_text() == source_content, "Target content does not match source"

    print("PASS test_sync_runtime_file_target")


def test_sync_runtime_json_field_enforce():
    """sync_project_tooling.py: json_field_enforce sets ensure fields, removes stale fields."""
    sync = _import_sync_script()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        lib_root = tmp / "library"
        project_root = tmp / "project"
        lib_root.mkdir()
        project_root.mkdir()

        # Create .beads/metadata.json with stale fields
        beads_dir = project_root / ".beads"
        beads_dir.mkdir()
        metadata = {
            "dolt_mode": "embedded",
            "database": "mydb",
            "backend": "embedded",
            "dolt_server_port": 3306,
            "dolt_server_user": "root",
            "server_host": "localhost",
        }
        meta_file = beads_dir / "metadata.json"
        meta_file.write_text(json.dumps(metadata, indent=2))

        entries = [
            {
                "name": "beads-server-mode",
                "description": "Enforce server mode",
                "target_kind": "json_field_enforce",
                "target_path": ".beads/metadata.json",
                "conditions": [{"file_exists": ".beads/metadata.json"}],
                "sync_strategy": "repair_fields",
                "conflict_policy": "canonical_wins",
                "fields": {
                    "ensure": {"dolt_mode": "server"},
                    "remove": ["database", "backend", "dolt_server_port", "dolt_server_user"],
                },
            }
        ]

        result = sync.sync_entries(entries, library_root=lib_root, project_root=project_root)
        assert result["synced"] >= 1, f"Expected at least 1 synced entry, got: {result}"

        updated = json.loads(meta_file.read_text())
        assert updated["dolt_mode"] == "server", "dolt_mode was not set to server"
        assert "database" not in updated, "stale field 'database' was not removed"
        assert "backend" not in updated, "stale field 'backend' was not removed"
        assert "dolt_server_port" not in updated, "stale field 'dolt_server_port' was not removed"
        assert "dolt_server_user" not in updated, "stale field 'dolt_server_user' was not removed"
        # Non-stale fields preserved
        assert updated.get("server_host") == "localhost", "non-stale field was incorrectly removed"

    print("PASS test_sync_runtime_json_field_enforce")


def test_sync_runtime_idempotent():
    """sync_project_tooling.py: running sync twice produces the same result."""
    sync = _import_sync_script()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        lib_root = tmp / "library"
        project_root = tmp / "project"
        lib_root.mkdir()
        project_root.mkdir()

        # Set up source
        source_content = "# Fleet PRIME\nIdempotency check."
        source_file = lib_root / "prime" / "PRIME.md"
        source_file.parent.mkdir(parents=True)
        source_file.write_text(source_content)

        (project_root / ".beads").mkdir()

        entries = [
            {
                "name": "beads-prime",
                "description": "Test prime entry",
                "target_kind": "file",
                "target_path": ".beads/PRIME.md",
                "source": "prime/PRIME.md",
                "conditions": [{"dir_exists": ".beads"}],
                "sync_strategy": "overwrite_if_source_newer",
                "conflict_policy": "canonical_wins",
            }
        ]

        # First run
        result1 = sync.sync_entries(entries, library_root=lib_root, project_root=project_root)
        target_file = project_root / ".beads" / "PRIME.md"
        content_after_first = target_file.read_text()

        # Second run
        result2 = sync.sync_entries(entries, library_root=lib_root, project_root=project_root)
        content_after_second = target_file.read_text()

        assert content_after_first == source_content, "First run: content mismatch"
        assert content_after_second == source_content, "Second run: content mismatch"
        assert content_after_first == content_after_second, "Idempotency: content changed between runs"

    print("PASS test_sync_runtime_idempotent")


# ---------------------------------------------------------------------------
# Main runner (no pytest required)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_project_tooling_section_accepted,
    test_project_tooling_requires_name,
    test_project_tooling_requires_description,
    test_project_tooling_requires_target_kind,
    test_project_tooling_requires_target_path,
    test_target_kind_enum,
    test_sync_strategy_enum,
    test_conflict_policy_enum,
    test_conditions_language,
    test_json_field_enforce_fields,
    test_full_beads_prime_example,
    test_library_yaml_has_project_tooling,
    test_sync_runtime_file_target,
    test_sync_runtime_json_field_enforce,
    test_sync_runtime_idempotent,
]


def main() -> int:
    pass_count = 0
    fail_count = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            pass_count += 1
        except AssertionError as e:
            print(f"FAIL {test_fn.__name__}: {e}")
            fail_count += 1
        except Exception as e:
            print(f"ERROR {test_fn.__name__}: {type(e).__name__}: {e}")
            fail_count += 1

    print(f"\n{pass_count} passed, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
