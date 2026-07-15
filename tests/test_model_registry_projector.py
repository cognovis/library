from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "lib" / "model-registry-projector.py"


def _module():
    spec = importlib.util.spec_from_file_location("model_registry_projector", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_projection_is_versioned_and_contains_gateway_fields() -> None:
    module = _module()
    source = yaml.safe_load((ROOT / "models.yaml").read_text(encoding="utf-8"))

    result = module.project_registry(source)
    by_model = {item["model"]: item for item in result["models"]}

    assert result["registry_version"] == source["runtime_registry_version"]
    assert by_model["gpt-5.6-sol"]["adapter"] == "codex-exec"
    assert by_model["gpt-5.6-terra"]["capabilities"] == [
        "implementation",
        "repository-analysis",
        "test-execution",
    ]
    assert "suitability_capabilities" not in by_model["gpt-5.6-sol"]
