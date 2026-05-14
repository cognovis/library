#!/usr/bin/env python3
"""Tests for Gas City pack export metadata validation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_EXPORT = REPO_ROOT / "scripts" / "validate-gascity-export.py"
VALIDATE_LIBRARY = REPO_ROOT / "scripts" / "validate-library.py"
SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "library.schema.json"


def _run(script: Path, data: dict, *extra: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(data, f)
        tmp_path = f.name
    try:
        return subprocess.run(
            [sys.executable, str(script), "--yaml", tmp_path, *extra],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _base_catalog(entry: dict) -> dict:
    return {
        "default_dirs": {
            "skills": [{"default": ".agents/skills/"}],
            "scripts": [{"default": ".agents/scripts/"}],
            "standards": [{"default": ".agents/standards/"}],
        },
        "library": {
            "skills": [entry],
            "scripts": [],
            "standards": [
                {
                    "name": "english-only",
                    "description": "English source-code rule.",
                    "source": "https://github.com/example/repo/blob/main/standards/english-only/english-only.md",
                }
            ],
        },
    }


def test_schema_accepts_nested_gascity_metadata():
    entry = {
        "name": "packable-skill",
        "description": "A packable skill.",
        "source": "https://github.com/example/repo/blob/main/skills/packable-skill/SKILL.md",
        "scripts": [
            {
                "path": "scripts/check.py",
                "role": "validator",
                "language": "python",
                "output_contract": "json-envelope",
            }
        ],
        "metadata": {
            "library": {
                "gascity": {
                    "exportable": True,
                    "target": "skill",
                    "pack": "cognovis-base",
                    "scope": "rig",
                    "session_class": "none",
                    "provider_neutral": True,
                    "requires": {
                        "binaries": ["bd"],
                        "env": [],
                        "standards": ["english-only"],
                    },
                }
            }
        },
    }
    result = _run(VALIDATE_LIBRARY, _base_catalog(entry), "--schema", str(SCHEMA_PATH))
    assert result.returncode == 0, result.stdout + result.stderr


def test_schema_accepts_dev_plane_product_counterpart_metadata():
    entry = {
        "name": "paired-skill",
        "description": "A dev-plane skill paired with product-plane work.",
        "source": "https://github.com/example/repo/blob/main/skills/paired-skill/SKILL.md",
        "metadata": {
            "library": {
                "plane": "dev",
                "product_counterpart": {
                    "repo": "mira",
                    "path": "runtime/agents/paired-skill.py",
                    "name": "paired-skill-runtime",
                    "primitive_type": "agent",
                },
            }
        },
    }
    result = _run(VALIDATE_LIBRARY, _base_catalog(entry), "--schema", str(SCHEMA_PATH))
    assert result.returncode == 0, result.stdout + result.stderr


def test_export_validator_rejects_product_plane_catalog_entry():
    entry = {
        "name": "runtime-agent",
        "description": "A product-plane runtime agent.",
        "source": "https://github.com/example/repo/blob/main/agents/runtime-agent.md",
        "metadata": {"library": {"plane": "product"}},
    }
    result = _run(VALIDATE_EXPORT, _base_catalog(entry), "--json")
    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    assert "metadata.library.plane must be 'dev'" in "\n".join(envelope["errors"])


def test_export_validator_accepts_valid_exportable_entry():
    entry = {
        "name": "packable-agent",
        "description": "A packable agent.",
        "source": "https://github.com/example/repo/blob/main/agents/packable-agent.md",
        "metadata": {
            "library": {
                "gascity": {
                    "exportable": True,
                    "target": "agent",
                    "pack": "cognovis-base",
                    "scope": "rig",
                    "session_class": "polecat",
                    "requires": {"standards": ["english-only"]},
                }
            }
        },
    }
    data = _base_catalog(entry)
    data["library"]["agents"] = [data["library"]["skills"].pop()]
    result = _run(VALIDATE_EXPORT, data, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "ok"


def test_export_validator_accepts_projection_shape():
    entry = {
        "name": "projectable-agent",
        "description": "An agent with PackV2 projection metadata.",
        "source": "https://github.com/example/repo/blob/main/agents/projectable-agent.md",
        "metadata": {
            "library": {
                "gascity": {
                    "exportable": True,
                    "projections": [
                        {
                            "target": "agent",
                            "pack": "cognovis-base",
                            "scope": "rig",
                            "session_class": "crew",
                            "target_path": "agents/projectable-agent.md",
                            "requires": {"standards": ["english-only"]},
                        }
                    ],
                }
            }
        },
    }
    data = _base_catalog(entry)
    data["library"]["agents"] = [data["library"]["skills"].pop()]
    result = _run(VALIDATE_LIBRARY, data, "--schema", str(SCHEMA_PATH))
    assert result.returncode == 0, result.stdout + result.stderr
    result = _run(VALIDATE_EXPORT, data, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "ok"


def test_export_validator_rejects_missing_target():
    entry = {
        "name": "broken-skill",
        "description": "A broken packable skill.",
        "source": "https://github.com/example/repo/blob/main/skills/broken-skill/SKILL.md",
        "metadata": {
            "library": {
                "gascity": {
                    "exportable": True,
                    "pack": "cognovis-base",
                    "scope": "rig",
                }
            }
        },
    }
    result = _run(VALIDATE_EXPORT, _base_catalog(entry), "--json")
    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    assert "missing 'target'" in "\n".join(envelope["errors"])


def test_export_validator_allows_non_exportable_entry_without_gascity_metadata():
    entry = {
        "name": "plain-skill",
        "description": "A normal Library skill without Gas City export metadata.",
        "source": "https://github.com/example/repo/blob/main/skills/plain-skill/SKILL.md",
    }
    result = _run(VALIDATE_EXPORT, _base_catalog(entry), "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "ok"


def test_pack_strict_validation_checks_targeted_non_exportable_projection():
    entry = {
        "name": "draft-projection",
        "description": "A draft projection that is only strict when a pack is targeted.",
        "source": "https://github.com/example/repo/blob/main/skills/draft-projection/SKILL.md",
        "metadata": {
            "library": {
                "gascity": {
                    "exportable": False,
                    "projections": [{"pack": "cognovis-base"}],
                }
            }
        },
    }
    result = _run(VALIDATE_EXPORT, _base_catalog(entry), "--json")
    assert result.returncode == 0, result.stdout + result.stderr

    result = _run(VALIDATE_EXPORT, _base_catalog(entry), "--json", "--pack", "cognovis-base")
    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    errors = "\n".join(envelope["errors"])
    assert "missing 'target'" in errors
    assert "missing 'scope'" in errors


def test_script_primitive_is_python_only():
    data = _base_catalog(
        {
            "name": "consumer",
            "description": "Consumes script.",
            "source": "https://github.com/example/repo/blob/main/skills/consumer/SKILL.md",
        }
    )
    data["library"]["scripts"] = [
        {
            "name": "validate-spec",
            "description": "Validate a spec.",
            "source": "https://github.com/example/repo/blob/main/scripts/validate-spec.py",
            "language": "python",
            "output_contract": "json-envelope",
            "metadata": {
                "library": {
                    "gascity": {
                        "exportable": True,
                        "target": "script",
                        "pack": "cognovis-specs",
                        "scope": "rig",
                    }
                }
            },
        }
    ]
    result = _run(VALIDATE_LIBRARY, data, "--schema", str(SCHEMA_PATH))
    assert result.returncode == 0, result.stdout + result.stderr
    result = _run(VALIDATE_EXPORT, data, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
