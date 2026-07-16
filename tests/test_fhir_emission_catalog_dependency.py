from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.catalog import load_catalog  # noqa: E402
from lib.resolver import resolve_requires  # noqa: E402


def test_fhir_emission_resolves_ig_authoring_standard_before_install() -> None:
    order = resolve_requires(
        load_catalog(REPO_ROOT),
        "skill",
        "fhir-emission",
        REPO_ROOT,
    )

    assert ("standard", "fhir-ig-authoring") in order
    assert order.index(("standard", "fhir-ig-authoring")) < order.index(
        ("skill", "fhir-emission")
    )
