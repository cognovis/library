"""Repository-health contract for the top-level project-only status command."""

from __future__ import annotations

import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "scripts" / "library.py"


def _run(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(repo / "home")
    return subprocess.run(
        ["uv", "run", str(LIBRARY), *arguments],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_status_reports_a_read_only_repository_health_matrix(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    sentinel = tmp_path / "unmanaged.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = _run(tmp_path, "status", "--offline", "--json")

    assert result.returncode == 2
    assert sentinel.read_text(encoding="utf-8") == "keep"
    payload = json.loads(result.stdout)
    assert payload["status"] == "repair_available"
    assert payload["overall"] == "repair_available"
    assert set(payload["health"]) == {
        "desired_state",
        "projections",
        "git_hygiene",
        "bootstrap",
        "unmanaged_primitives",
    }
    assert payload["health"]["desired_state"]["status"] == "missing"
    assert payload["health"]["git_hygiene"]["status"] == "repair_available"
    assert payload["health"]["bootstrap"]["status"] in {"ready", "repair_available"}


def test_status_uses_the_packaged_catalog_in_a_consumer_repository(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".library.lock").write_text(
        """schema_version: 2
migration: {prune_ack_required: false}
requested_roots: []
receipts: []
installed: []
""",
        encoding="utf-8",
    )

    result = _run(tmp_path, "status", "--offline", "--json")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["health"]["desired_state"] == {
        "status": "healthy",
        "requested_roots": [],
        "receipts": 0,
        "freshness": "current",
        "resolution_blockers": [],
        "pending_reconciliation": False,
    }


def test_status_uses_trusted_catalog_for_canonical_workspace_roots(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text(
        "catalog_identity: https://github.com/cognovis/cognovis-pi\n"
        "sources:\n"
        "  catalogs: []\n"
        "  marketplaces: []\n"
        "library:\n"
        "  workspaces: []\n",
        encoding="utf-8",
    )

    initialized = _run(tmp_path, "init", "--json")
    status = _run(tmp_path, "status", "--offline", "--json")

    assert initialized.returncode == 0, initialized.stderr or initialized.stdout
    payload = json.loads(status.stdout)
    desired_state = payload["health"]["desired_state"]
    assert desired_state["status"] == "healthy"
    assert desired_state["freshness"] == "current"
    assert desired_state["resolution_blockers"] == []

    lock_path = tmp_path / ".library.lock"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["requested_roots"].append(
        {
            "id": "workspace:https://github.com/cognovis/library#retired-cursor",
            "type": "workspace",
            "name": "retired-cursor",
            "scope": "project",
            "catalog_identity": "https://github.com/cognovis/library",
            "catalog_name": "library-platform",
            "requested_ref": "library-platform:retired-cursor",
        }
    )
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

    retired_status = _run(tmp_path, "status", "--offline", "--json")
    retired_desired = json.loads(retired_status.stdout)["health"]["desired_state"]
    assert retired_desired["status"] == "repair_available"
    assert retired_desired["freshness"] == "stale"
    assert any("retired-cursor" in blocker for blocker in retired_desired["resolution_blockers"])
    assert all(
        "Unknown source catalog 'library-platform'" not in blocker
        for blocker in retired_desired["resolution_blockers"]
    )


def test_status_uses_exit_three_for_unmanaged_supported_harness_content(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    unmanaged = tmp_path / ".agents" / "skills" / "user-owned" / "SKILL.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text("# User owned\n", encoding="utf-8")

    result = _run(tmp_path, "status", "--offline", "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "decision_required"
    assert payload["health"]["unmanaged_primitives"] == {
        "status": "decision_required",
        "paths": [".agents/skills/user-owned/SKILL.md"],
    }


def test_status_reports_unmanaged_supported_primitive_kinds(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    paths = (
        ".agents/skills/nested/user-owned/SKILL.md",
        ".claude/agents/user-owned.md",
        ".codex/agents/user-owned.toml",
        ".agents/standards/user-owned/",
        ".claude/commands/user-owned.md",
        ".claude/hooks/user-owned.sh",
        ".agents/pi/extensions/user-owned/",
        ".agents/pi/profiles/user-owned/",
    )
    source_paths = (
        ".agents/skills/nested/user-owned/SKILL.md",
        ".claude/agents/user-owned.md",
        ".codex/agents/user-owned.toml",
        ".agents/standards/user-owned/standard.md",
        ".claude/commands/user-owned.md",
        ".claude/hooks/user-owned.sh",
        ".agents/pi/extensions/user-owned/index.ts",
        ".agents/pi/profiles/user-owned/profile.json",
    )
    for relative in source_paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("user-owned\n", encoding="utf-8")

    result = _run(tmp_path, "status", "--offline", "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["health"]["unmanaged_primitives"] == {
        "status": "decision_required",
        "paths": sorted(paths),
    }


def test_status_classifies_unmanaged_bundles_once_and_ignores_tracked_bundles(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    unmanaged_bundle = tmp_path / ".agents" / "pi" / "extensions" / "operator-extension"
    for name in ("index.ts", "internal.ts"):
        target = unmanaged_bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("operator-owned\n", encoding="utf-8")
    tracked_bundle = tmp_path / ".agents" / "pi" / "extensions" / "repository-extension"
    for name in ("index.ts", "internal.ts"):
        target = tracked_bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("repository-owned\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", str(tracked_bundle)], check=True)

    result = _run(tmp_path, "status", "--offline", "--json")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["health"]["unmanaged_primitives"] == {
        "status": "decision_required",
        "paths": [".agents/pi/extensions/operator-extension/"],
    }


def test_status_reports_receipt_drift_and_gitignore_hygiene_without_mutation(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    target = tmp_path / ".agents" / "skills" / "owned" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("changed\n", encoding="utf-8")
    (tmp_path / ".library.lock").write_text(
        """schema_version: 2
migration:
  prune_ack_required: false
requested_roots:
  - id: skill:owned
    type: skill
    name: owned
    scope: project
receipts:
  - id: skill:owned@1.0.0
    type: skill
    name: owned
    scope: project
    owners_cache: [skill:owned]
    targets:
      - path: .agents/skills/owned/SKILL.md
        kind: file
        content_sha256: """ + sha256(b"expected\n").hexdigest() + """
installed: []
""",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        """# BEGIN Library-managed project installs
/.library.lock.lock
/.library.lock.workspace-journal.json
/.library.lock.workspace-lock
/.library.lock.workspace-rollback
/.agents/skills/owned/SKILL.md
/stale-generated-target
# END Library-managed project installs
""",
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")

    result = _run(tmp_path, "status", "--offline", "--json")

    assert result.returncode == 2
    assert target.read_text(encoding="utf-8") == before
    payload = json.loads(result.stdout)
    assert payload["health"]["projections"] == {
        "status": "repair_available",
        "missing": [],
        "drifted": [".agents/skills/owned/SKILL.md"],
        "conflicting": [],
        "orphaned": [],
    }
    assert payload["health"]["git_hygiene"]["stale_managed_paths"] == [
        "stale-generated-target"
    ]


def test_status_marks_an_unresolved_workspace_as_stale_fresh_desired_state(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    (tmp_path / ".library.lock").write_text(
        """schema_version: 2
migration: {prune_ack_required: false}
requested_roots:
  - id: workspace:https://example.invalid/catalog#missing
    type: workspace
    name: missing
    scope: project
    requested_ref: missing
receipts: []
installed: []
""",
        encoding="utf-8",
    )

    result = _run(tmp_path, "status", "--offline", "--json")

    assert result.returncode == 2
    desired = json.loads(result.stdout)["health"]["desired_state"]
    assert desired["freshness"] == "stale"
    assert "missing" in desired["resolution_blockers"][0]


def test_status_accepts_escaped_managed_gitignore_targets(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "library.yaml").write_text("library: {}\n", encoding="utf-8")
    target = tmp_path / ".agents" / "skills" / "my#skill" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("owned\n", encoding="utf-8")
    (tmp_path / ".library.lock").write_text(
        """schema_version: 2
migration: {prune_ack_required: false}
requested_roots:
  - id: skill:my#skill
    type: skill
    name: my#skill
    scope: project
receipts:
  - id: skill:my#skill@1.0.0
    type: skill
    name: my#skill
    scope: project
    owners_cache: [skill:my#skill]
    targets:
      - path: .agents/skills/my#skill/SKILL.md
        kind: file
        content_sha256: """ + sha256(b"owned\n").hexdigest() + """
installed: []
""",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        """# BEGIN Library-managed project installs
/.library.lock.lock
/.library.lock.workspace-journal.json
/.library.lock.workspace-lock
/.library.lock.workspace-rollback
/.agents/skills/my\\#skill/SKILL.md
# END Library-managed project installs
""",
        encoding="utf-8",
    )

    result = _run(tmp_path, "status", "--offline", "--json")

    hygiene = json.loads(result.stdout)["health"]["git_hygiene"]
    assert hygiene["status"] == "clean"
    assert hygiene["missing_managed_paths"] == []
    assert hygiene["stale_managed_paths"] == []
