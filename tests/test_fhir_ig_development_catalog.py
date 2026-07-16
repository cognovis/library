from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.resolver import resolve_requires  # noqa: E402


def test_fhir_ig_development_resolves_its_standard_and_neighbor_skills() -> None:
    order = resolve_requires(
        load_catalog(REPO_ROOT),
        "skill",
        "fhir-ig-development",
        REPO_ROOT,
    )

    required = {
        ("standard", "fhir-ig-authoring"),
        ("standard", "judge-layer"),
        ("skill", "fhir-emission"),
        ("skill", "aidbox-ig-development"),
    }
    assert required.issubset(set(order))
    for dependency in required:
        assert order.index(dependency) < order.index(("skill", "fhir-ig-development"))
