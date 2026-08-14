"""The control plane is distributable as a uv tool, not a global Library skill."""

from __future__ import annotations

import os
import subprocess
import json
import shutil
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _git_commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Fixture", "-c",
         "user.email=fixture@example.invalid", "commit", "-qm", message],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _copy_tracked_platform(source: Path, target: Path) -> None:
    target.mkdir()
    tracked = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for encoded in tracked:
        if not encoded:
            continue
        relative = Path(os.fsdecode(encoded))
        origin = source / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_symlink():
            destination.symlink_to(origin.readlink())
        else:
            shutil.copy2(origin, destination)


def _write_fresh_machine_sources(tmp_path: Path) -> tuple[Path, Path]:
    platform = tmp_path / "platform-source"
    core = tmp_path / "core-source"
    _copy_tracked_platform(REPO_ROOT, platform)
    core.mkdir()
    for name in ("cognovis-beads", "inject-standards", "ob-cli"):
        skill = core / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\n# {name}\n", encoding="utf-8"
        )
    library_skill = platform / "skills" / "library"
    library_skill.mkdir(parents=True, exist_ok=True)
    shutil.copy2(platform / "SKILL.md", library_skill / "SKILL.md")

    subprocess.run(["git", "init", "--quiet", str(core)], check=True)
    core_pin = _git_commit(core, "fixture core")

    catalog = {
        "catalog_identity": "https://github.com/cognovis/library",
        "default_dirs": {
            "skills": [
                {"default": ".agents/skills/"},
                {"claude_bridge": ".claude/skills/"},
            ]
        },
        "sources": {
            "catalogs": [
                {
                    "name": "library-platform",
                    "source": "https://github.com/cognovis/library",
                    "content_types": ["skills", "workspaces"],
                },
                {
                    "name": "cognovis-library-core",
                    "source": "https://github.com/cognovis/library-core",
                    "local_path": "/missing/cognovis-library-core",
                    "content_types": ["skills"],
                },
            ],
            "marketplaces": [],
        },
        "library": {
            "skills": [
                {
                    "name": "library",
                    "description": "Fixture Library skill.",
                    "version": "1.0.0",
                    "source": "https://github.com/cognovis/library/tree/main/skills/library",
                    "metadata": {"library": {"source_catalog": "library-platform"}},
                },
                *[
                    {
                        "name": name,
                        "description": "Fixture core skill.",
                        "version": "1.0.0",
                        "source": f"https://github.com/cognovis/library-core/tree/main/skills/{name}",
                        "metadata": {
                            "library": {"source_catalog": "cognovis-library-core"}
                        },
                    }
                    for name in ("cognovis-beads", "inject-standards", "ob-cli")
                ],
            ],
            "workspaces": [],
        },
    }
    (platform / "library.yaml").write_text(
        yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8"
    )
    subprocess.run(["git", "init", "--quiet", str(platform)], check=True)
    platform_pin = _git_commit(platform, "fixture platform content")
    workspace_manifest = {
        "name": "cognovis-base",
        "description": "Fresh-machine fixture Workspace.",
        "schema_version": 2,
        "version": "1.0.0",
        "status": "stable",
        "catalogs": [
            {
                "alias": "platform",
                "identity": "https://github.com/cognovis/library",
                "pin": {"kind": "commit", "value": platform_pin},
            },
            {
                "alias": "core",
                "identity": "https://github.com/cognovis/library-core",
                "pin": {"kind": "commit", "value": core_pin},
            },
        ],
        "roots": [
            {"type": "skill", "name": "library", "catalog": "platform"},
            *[
                {"type": "skill", "name": name, "catalog": "core"}
                for name in ("cognovis-beads", "inject-standards", "ob-cli")
            ],
        ],
        "metadata": {
            "library": {
                "source_catalog": "library-platform",
                "source_commit": platform_pin,
            }
        },
    }
    catalog["library"]["workspaces"] = [workspace_manifest]
    (platform / "workspaces" / "cognovis-base.yaml").write_text(
        yaml.safe_dump(workspace_manifest, sort_keys=False), encoding="utf-8"
    )
    (platform / "library.yaml").write_text(
        yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8"
    )
    _git_commit(platform, "fixture Workspace")
    return platform, core


def test_uv_tool_install_exposes_the_bootstrap_console_scripts_without_source_links(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)

    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    version = subprocess.run(
        [str(bin_dir / "library"), "--version"], env=env, capture_output=True,
        text=True, check=False,
    )

    assert install.returncode == 0, install.stderr
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("library 2.0.0")
    for command in ("library", "cld", "cdx"):
        executable = bin_dir / command
        assert executable.is_file()
        assert not executable.resolve().is_relative_to(REPO_ROOT)
    assert not (tool_dir / "library" / ".agents" / "skills" / "library").exists()


def test_regression_packaged_cdx_resolves_bundled_context_renderer(
    tmp_path: Path,
) -> None:
    """Packaged cdx must resolve resources beside scripts/bin, not scripts/scripts."""
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    repo = tmp_path / "repo"
    worktree_root = tmp_path / "worktrees"
    worktree = worktree_root / "bead-CL-smoke"
    called_file = tmp_path / "codex-called"
    repo.mkdir()
    (repo / ".git").mkdir()
    worktree.mkdir(parents=True)

    bd_mock = _write_executable(
        tmp_path / "bd-mock",
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "bead_id = args[1]\n"
        "if '--children' in args:\n"
        "    print(json.dumps({bead_id: []}))\n"
        "else:\n"
        "    print(json.dumps([{'id': bead_id, 'title': 'Smoke bead', 'metadata': {}}]))\n",
    )
    git_mock = _write_executable(
        tmp_path / "git-mock",
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['rev-parse', '--show-toplevel']:\n"
        "    print(os.environ['GIT_REPO_ROOT'])\n"
        "elif args[:3] == ['worktree', 'list', '--porcelain']:\n"
        "    print(f\"worktree {os.environ['GIT_WORKTREE']}\")\n",
    )
    codex_mock = _write_executable(
        tmp_path / "codex-mock",
        f"#!{sys.executable}\n"
        "import os, pathlib\n"
        "pathlib.Path(os.environ['CODEX_CALLED_FILE']).write_text('called', encoding='utf-8')\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "UV_TOOL_DIR": str(tool_dir),
            "UV_TOOL_BIN_DIR": str(bin_dir),
            "BD_BIN": str(bd_mock),
            "GIT_BIN": str(git_mock),
            "GIT_REPO_ROOT": str(repo),
            "GIT_WORKTREE": str(worktree),
            "CDX_WORKTREE_ROOT": str(worktree_root),
            "CODEX_BIN": str(codex_mock),
            "CODEX_CALLED_FILE": str(called_file),
            "CLD_COMPACT_OUTPUT": "0",
        }
    )

    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    launched = subprocess.run(
        [str(bin_dir / "cdx"), "-bq", "CL-smoke"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert launched.returncode == 0, launched.stderr
    assert called_file.read_text(encoding="utf-8") == "called"
    assert "bead context envelope renderer not found" not in launched.stderr


def test_uv_tool_install_carries_the_catalog_for_commands_outside_a_checkout(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)

    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    listed = subprocess.run(
        [str(bin_dir / "library"), "skill", "list", "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert listed.returncode == 0, listed.stderr
    assert isinstance(json.loads(listed.stdout), list)

    initialized = subprocess.run(
        [str(bin_dir / "library"), "init", "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert initialized.returncode == 0, initialized.stderr or initialized.stdout
    initialized_payload = json.loads(initialized.stdout)
    assert initialized_payload["status"] == "applied"
    assert initialized_payload["reference"] == "library-platform:cognovis-base"

    workspaces = subprocess.run(
        [str(bin_dir / "library"), "workspace", "list", "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert workspaces.returncode == 0, workspaces.stderr
    assert json.loads(workspaces.stdout)["workspaces"]

    catalog_consumer = tmp_path / "catalog-consumer"
    catalog_consumer.mkdir()
    (catalog_consumer / "library.yaml").write_text(
        yaml.safe_dump(
            {
                "catalog_identity": "https://github.com/cognovis/cognovis-pi",
                "sources": {"catalogs": [], "marketplaces": []},
                "library": {"workspaces": []},
            },
            sort_keys=False,
        )
    )
    subprocess.run(["git", "init", "--quiet", str(catalog_consumer)], check=True)

    catalog_initialized = subprocess.run(
        [str(bin_dir / "library"), "init", "--json"],
        cwd=catalog_consumer,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert catalog_initialized.returncode == 0, (
        catalog_initialized.stderr or catalog_initialized.stdout
    )
    assert json.loads(catalog_initialized.stdout)["reference"] == (
        "library-platform:cognovis-base"
    )


def test_uv_tool_install_uses_packaged_catalog_when_tool_dir_is_nested_in_consumer(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "catalog-consumer"
    consumer.mkdir()
    (consumer / "library.yaml").write_text(
        yaml.safe_dump(
            {
                "catalog_identity": "https://github.com/cognovis/cognovis-pi",
                "sources": {"catalogs": [], "marketplaces": []},
                "library": {"workspaces": []},
            },
            sort_keys=False,
        )
    )
    subprocess.run(["git", "init", "--quiet", str(consumer)], check=True)
    tool_dir = consumer / ".tools"
    bin_dir = consumer / ".bin"
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)

    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    initialized = subprocess.run(
        [str(bin_dir / "library"), "init", "--json"],
        cwd=consumer,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert initialized.returncode == 0, initialized.stderr or initialized.stdout
    assert json.loads(initialized.stdout)["reference"] == (
        "library-platform:cognovis-base"
    )


def test_uv_tool_install_init_ignores_consumer_cognovis_base_shadow(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    consumer = tmp_path / "catalog-consumer"
    consumer.mkdir()
    for name in ("fixture-skill", "fixture-support"):
        skill = consumer / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
    (consumer / "library.yaml").write_text(
        yaml.safe_dump(
            {
                "catalog_identity": "https://github.com/example/consumer",
                "sources": {
                    "catalogs": [
                        {
                            "name": "fixture-catalog",
                            "source": "https://github.com/example/fixture-catalog",
                            "local_path": str(consumer),
                            "content_types": ["skills", "workspaces"],
                        }
                    ],
                    "marketplaces": [],
                },
                "library": {
                    "skills": [
                        {
                            "name": name,
                            "description": f"Fixture {name}.",
                            "version": "1.0.0",
                            "source": (
                                "https://github.com/example/fixture-catalog/tree/main/"
                                f"skills/{name}"
                            ),
                            "metadata": {
                                "library": {"source_catalog": "fixture-catalog"}
                            },
                        }
                        for name in ("fixture-skill", "fixture-support")
                    ],
                    "workspaces": [
                        {
                            "name": "cognovis-base",
                            "description": "Shadow Workspace fixture.",
                            "schema_version": 1,
                            "version": "1.0.0",
                            "status": "stable",
                            "roots": [
                                {"type": "skill", "name": "fixture-skill"},
                                {"type": "skill", "name": "fixture-support"},
                            ],
                            "metadata": {
                                "library": {"source_catalog": "fixture-catalog"}
                            },
                        }
                    ],
                },
            },
            sort_keys=False,
        )
    )
    subprocess.run(["git", "init", "--quiet", str(consumer)], check=True)
    _git_commit(consumer, "fixture consumer catalog")
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)

    install = subprocess.run(
        ["uv", "tool", "install", str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    initialized = subprocess.run(
        [str(bin_dir / "library"), "init", "--json"],
        cwd=consumer,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert initialized.returncode == 0, initialized.stderr or initialized.stdout
    assert json.loads(initialized.stdout)["reference"] == (
        "library-platform:cognovis-base"
    )


def test_fresh_machine_installer_bootstraps_sources_and_project_workspace(
    tmp_path: Path,
) -> None:
    platform, core = _write_fresh_machine_sources(tmp_path)
    home = tmp_path / "home"
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    source_dir = tmp_path / "managed-sources"
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "UV_TOOL_DIR": str(tool_dir),
            "UV_TOOL_BIN_DIR": str(bin_dir),
        }
    )

    installed = subprocess.run(
        [
            "bash",
            str(platform / "install.sh"),
            "--fresh",
            "--platform-source",
            str(platform),
            "--core-source",
            str(core),
            "--source-dir",
            str(source_dir),
            "--project",
            str(project),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    installed_again = subprocess.run(
        installed.args,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    repository_status = subprocess.run(
        [str(bin_dir / "library"), "status", "--project", str(project), "--offline", "--json"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    workspace_status = subprocess.run(
        [
            str(bin_dir / "library"),
            "workspace",
            "status",
            "--all",
            "--scope",
            "project",
            "--target-project",
            str(project),
            "--harness",
            "all",
            "--json",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert installed_again.returncode == 0, (
        installed_again.stderr or installed_again.stdout
    )
    assert (bin_dir / "library").is_file()
    assert (source_dir / "library-platform" / ".git").is_dir()
    assert (source_dir / "cognovis-library-core" / ".git").is_dir()
    assert (tmp_path / "config" / "library" / "catalog-sources.json").is_file()
    assert (home / ".config" / "library" / "bootstrap.json").is_file()
    assert (project / ".library.lock").is_file()
    for name in ("library", "cognovis-beads", "inject-standards", "ob-cli"):
        assert (project / ".agents" / "skills" / name / "SKILL.md").is_file()
    assert not (home / ".agents" / "skills").exists()
    assert repository_status.returncode == 0, (
        repository_status.stderr or repository_status.stdout
    )
    repository_payload = json.loads(repository_status.stdout)
    assert repository_payload["status"] == "healthy"
    assert repository_payload["health"]["desired_state"]["status"] == "healthy"
    assert repository_payload["health"]["projections"]["status"] == "clean"
    assert repository_payload["health"]["bootstrap"]["status"] == "ready"
    assert workspace_status.returncode == 0, workspace_status.stderr or workspace_status.stdout
    assert json.loads(workspace_status.stdout)["status"] == "converged"


def test_fresh_machine_installer_refuses_an_incomplete_managed_checkout(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "managed-sources"
    incomplete = source_dir / "library-platform"
    (incomplete / ".git").mkdir(parents=True)
    sentinel = incomplete / "partial-clone-state"
    sentinel.write_text("preserve for operator recovery\n", encoding="utf-8")
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "UV_TOOL_DIR": str(tmp_path / "tools"),
            "UV_TOOL_BIN_DIR": str(bin_dir),
        }
    )

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "install.sh"),
            "--fresh",
            "--platform-source",
            str(REPO_ROOT),
            "--core-source",
            str(REPO_ROOT),
            "--source-dir",
            str(source_dir),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "managed checkout is incomplete" in result.stderr
    assert "Move it aside after preserving any needed files" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve for operator recovery\n"
    assert not (bin_dir / "library").exists()
    assert not (tmp_path / "config" / "library" / "catalog-sources.json").exists()


def test_bootstrap_install_writes_only_the_enumerated_global_contract(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    installed = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr or installed.stdout
    assert (home / ".agents" / "AGENTS.md").is_file()
    assert (home / ".claude" / "CLAUDE.md").is_file()
    assert (home / ".agents" / "orchestrator-config.yml").is_file()
    assert (home / ".claude.json").is_file()
    assert (home / ".codex" / "config.toml").is_file()
    assert (home / ".pi" / "settings.json").is_file()
    assert "open-brain" in (home / ".codex" / "config.toml").read_text()
    assert "open-brain" in (home / ".claude.json").read_text()
    assert "open-brain" in (home / ".pi" / "settings.json").read_text()
    assert (home / ".config" / "library" / "bootstrap.json").is_file()
    assert not (home / ".agents" / "skills" / "library").exists()
    assert json.loads(installed.stdout)["status"] == "ok"


def test_bootstrap_install_adopts_existing_operator_owned_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    agents = home / ".agents" / "AGENTS.md"
    runtime = home / ".agents" / "orchestrator-config.yml"
    claude = home / ".claude" / "CLAUDE.md"
    for path, text in (
        (agents, "# Operator rules\n"),
        (runtime, "default_profile: operator\n"),
        (claude, "# Operator Claude rules\n\n@~/.agents/AGENTS.md\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert agents.read_text(encoding="utf-8") == "# Operator rules\n"
    assert runtime.read_text(encoding="utf-8") == "default_profile: operator\n"
    assert claude.read_text(encoding="utf-8") == (
        "# Operator Claude rules\n\n@~/.agents/AGENTS.md\n"
    )
    payload = json.loads(result.stdout)
    assert payload["conflicts"] == []
    assert (home / ".config" / "library" / "bootstrap.json").is_file()

    status = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "status", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert status.returncode == 0
    assert json.loads(status.stdout)["bootstrap"] == {"status": "ready", "missing": []}


def test_bootstrap_install_adopts_library_origin_mcp_registrations(tmp_path: Path) -> None:
    home = tmp_path / "home"
    claude_config = home / ".claude.json"
    codex_config = home / ".codex" / "config.toml"
    codex_config.parent.mkdir(parents=True)
    claude_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "open-brain": {
                        "type": "http",
                        "url": "https://open-brain.sussdorff.org/mcp",
                        "_origin": "library:mcp:open-brain",
                    },
                    "operator-server": {"type": "http", "url": "https://operator.example/mcp"},
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    codex_config.write_text(
        "model = \"operator-model\"\n\n"
        "[mcp_servers.open-brain]\n"
        "url = \"https://open-brain.sussdorff.org/mcp\"\n"
        "_origin = \"library:mcp:open-brain\"\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["conflicts"] == []
    assert (home / ".config" / "library" / "bootstrap.json").is_file()
    assert json.loads(claude_config.read_text(encoding="utf-8"))["mcpServers"]["operator-server"] == {
        "type": "http",
        "url": "https://operator.example/mcp",
    }
    assert "model = \"operator-model\"" in codex_config.read_text(encoding="utf-8")


def test_bootstrap_install_preflights_mcp_configs_before_any_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    codex_config = home / ".codex" / "config.toml"
    codex_config.parent.mkdir(parents=True)
    codex_config.write_text("not valid = [toml\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["HOME"] = str(home)

    result = subprocess.run(
        ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["conflicts"] == ["openbrain_codex"]
    assert not (home / ".agents" / "AGENTS.md").exists()
    assert not (home / ".claude" / "CLAUDE.md").exists()
    assert not (home / ".agents" / "orchestrator-config.yml").exists()
    assert not (home / ".config" / "library" / "bootstrap.json").exists()


def test_bootstrap_remove_refuses_drifted_mcp_configuration(tmp_path: Path) -> None:
    home = tmp_path / "home"
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    command = ["uv", "run", str(REPO_ROOT / "scripts" / "library.py"), "bootstrap"]

    installed = subprocess.run(
        [*command, "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    codex_config = home / ".codex" / "config.toml"
    codex_config.write_text(
        "[mcp_servers.open-brain]\nurl = \"https://operator.example/mcp\"\n",
        encoding="utf-8",
    )
    removed = subprocess.run(
        [*command, "remove", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    assert removed.returncode == 2
    assert json.loads(removed.stdout)["conflicts"] == ["openbrain_codex"]
    assert (home / ".agents" / "AGENTS.md").is_file()
    assert (home / ".config" / "library" / "bootstrap.json").is_file()


def test_status_uses_the_bootstrap_manifest_to_report_mcp_drift(tmp_path: Path) -> None:
    home = tmp_path / "home"
    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    for command in ("library", "cld", "cdx"):
        executable = command_dir / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    command = ["uv", "run", str(REPO_ROOT / "scripts" / "library.py")]

    installed = subprocess.run(
        [*command, "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    status_environment = environment | {"PATH": f"{command_dir}{os.pathsep}{environment['PATH']}"}
    ready = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    (home / ".pi" / "settings.json").write_text("{}\n", encoding="utf-8")
    drifted = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    assert json.loads(ready.stdout)["health"]["bootstrap"] == {
        "status": "ready",
        "missing": [],
    }
    assert json.loads(drifted.stdout)["health"]["bootstrap"] == {
        "status": "repair_available",
        "missing": ["openbrain_pi"],
    }


def test_bootstrap_status_and_repository_status_share_operator_safe_health(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    for command_name in ("library", "cld", "cdx"):
        executable = command_dir / command_name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    status_environment = environment | {"PATH": f"{command_dir}{os.pathsep}{environment['PATH']}"}
    command = ["uv", "run", str(REPO_ROOT / "scripts" / "library.py")]

    installed = subprocess.run(
        [*command, "bootstrap", "install", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    for path, content in (
        (home / ".agents" / "AGENTS.md", "# Operator rules\n"),
        (
            home / ".claude" / "CLAUDE.md",
            "# Operator Claude rules\n\n@~/.agents/AGENTS.md\n",
        ),
        (home / ".agents" / "orchestrator-config.yml", "default_profile: operator\n"),
    ):
        path.write_text(content, encoding="utf-8")
    bootstrap_ready = subprocess.run(
        [*command, "bootstrap", "status", "--json"],
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    repository_ready = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    (home / ".pi" / "settings.json").write_text("{}\n", encoding="utf-8")
    bootstrap_drifted = subprocess.run(
        [*command, "bootstrap", "status", "--json"],
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    repository_drifted = subprocess.run(
        [*command, "status", "--offline", "--json"],
        cwd=REPO_ROOT,
        env=status_environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    assert bootstrap_ready.returncode == 0
    assert json.loads(bootstrap_ready.stdout)["bootstrap"] == {
        "status": "ready",
        "missing": [],
    }
    assert json.loads(repository_ready.stdout)["health"]["bootstrap"] == {
        "status": "ready",
        "missing": [],
    }
    assert bootstrap_drifted.returncode == 2
    assert json.loads(bootstrap_drifted.stdout)["bootstrap"] == {
        "status": "repair_available",
        "missing": ["openbrain_pi"],
    }
    assert json.loads(repository_drifted.stdout)["health"]["bootstrap"] == {
        "status": "repair_available",
        "missing": ["openbrain_pi"],
    }
