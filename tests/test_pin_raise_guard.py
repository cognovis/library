"""No agent raises a pin or grants admission by itself (ADR-0011, `CL-lt51`).

The shipped guard is `.dcg/packs/library-pin-raise-guard.yaml`, loaded through
the repository-scoped `custom_paths` entry in the operator's dcg configuration.
It is one half of a two-part control and only works as one:

- the guard **stops** the agent at the moment it would adopt foreign content;
- `DecisionPacket.approval_command` **tells** the agent what to hand its human.

A guard with no rendered remedy produces an agent that improvises a command, and
a rendered remedy with no guard produces one that just runs it. This module holds
down both halves, and the shape that matters most: the *preparation* verbs stay
allowed. A guard that blocked the whole flow would be an outage, and an outage
gets switched off.

The pack is evaluated here with Python's own regex engine rather than through
`dcg`, so the assertions run on a machine that has no dcg installed. When dcg
*is* present the same commands are put through it as well, because the pack is
only a control if the engine that ships it agrees.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

PACK = REPO_ROOT / ".dcg" / "packs" / "library-pin-raise-guard.yaml"

BLOCKED = (
    "library marketplace update-approve steward@abcdef --operator o --reason r",
    "library marketplace update-approve steward@abcdef --item x --operator o --reason r",
    "uv run python scripts/library.py marketplace update-approve p --operator o --reason r",
    "cd /tmp && library marketplace update-approve p --operator o --reason r",
    "library admission grant --identity a --digest sha256:0 --type skill "
    "--operator o --reason r --no-permissions",
    "uv run python scripts/library.py admission grant --identity a --digest d "
    "--type workflow --operator o --reason r",
    "library marketplace update steward --against-recommendation",
)

ALLOWED = (
    "library marketplace update matt-pocock-skills",
    "library marketplace update matt-pocock-skills --json",
    "uv run python scripts/library.py marketplace update steward --item skills/x",
    "library marketplace update-show steward@abcdef",
    "library marketplace update-show steward@abcdef --content",
    "library marketplace update-list --json",
    "library marketplace update-reject steward@abcdef --operator o --reason r",
    "library admission deny --identity a --digest d --type skill --operator o --reason r",
    "library admission list --json",
    "library admission show --identity a",
    "library marketplace inventory disler",
    "library marketplace status",
    "library marketplace install steward skills/x",
)


@pytest.fixture(scope="module")
def pack() -> dict:
    return yaml.safe_load(PACK.read_text(encoding="utf-8"))


def _verdict(pack: dict, command: str) -> str:
    """Block unless a safe pattern claims the command, matching dcg's precedence."""
    for entry in pack.get("safe_patterns", ()):
        if re.search(entry["pattern"], command):
            return "allowed"
    for entry in pack.get("destructive_patterns", ()):
        if re.search(entry["pattern"], command):
            return "blocked"
    return "allowed"


class TestPackShape:
    def test_the_pack_declares_its_identity_and_every_rule_explains_itself(self, pack):
        assert pack["schema_version"] == 1
        assert pack["id"] == "cognovis.library_pin_raise"
        assert pack["destructive_patterns"], "a guard with no rules guards nothing"
        for entry in pack["destructive_patterns"]:
            assert entry["severity"] == "critical"
            assert entry["description"].strip()
            # The explanation is what an agent reads at the moment it is stopped.
            # One that only says "blocked" produces an agent that looks for a way
            # around; one that names the human act produces the handoff.
            assert "human" in entry["explanation"].lower()
            re.compile(entry["pattern"])
        for entry in pack.get("safe_patterns", ()):
            assert entry["description"].strip()
            re.compile(entry["pattern"])

    def test_the_rules_name_the_verbs_the_cli_actually_registers(self, pack):
        from lib.providers.executable_admission import ADMISSION_COMMAND, GRANT_VERB
        from lib.providers.update_admission import (
            UPDATE_APPROVE_VERB,
            UPDATE_COMMAND,
            UPDATE_VERB,
        )

        source = PACK.read_text(encoding="utf-8")
        # Rendered from the same constants the parser registers, for the reason
        # the admission refusal is: a guard that names a renamed verb guards a
        # command that no longer exists.
        assert UPDATE_APPROVE_VERB in source
        assert UPDATE_COMMAND in source
        assert UPDATE_VERB in source
        assert ADMISSION_COMMAND in source
        assert GRANT_VERB in source


class TestVerdicts:
    @pytest.mark.parametrize("command", BLOCKED)
    def test_adoption_is_blocked(self, pack, command):
        assert _verdict(pack, command) == "blocked", command

    @pytest.mark.parametrize("command", ALLOWED)
    def test_preparation_and_refusal_stay_available(self, pack, command):
        assert _verdict(pack, command) == "allowed", command


class TestRenderedRemedy:
    def test_the_packet_renders_the_command_the_guard_blocks(self):
        """The two halves are one control, so they have to name the same thing."""
        from lib.providers.update_admission import (
            OPERATOR_PLACEHOLDER,
            ChangedItem,
            ChangeSet,
            DecisionPacket,
        )

        change_set = ChangeSet(
            provider_identity="https://example.invalid/steward",
            observed_at="2026-08-10T09:00:00Z",
            first_import=True,
            items=(
                ChangedItem(
                    qualified_identity="https://example.invalid/steward#skills/x",
                    upstream_id="skills/x",
                    library_type="skill",
                    library_name="x",
                    change="added",
                    pinned_digest=None,
                    fetched_digest="sha256:" + "a" * 64,
                    byte_size=4,
                    diff="",
                    content={"SKILL.md": b"body"},
                ),
            ),
        )
        packet = DecisionPacket(
            packet_id="steward@0123456789abcdef",
            provider_identity="https://example.invalid/steward",
            created_at="2026-08-10T09:00:00Z",
            change_set=change_set,
            scans={},
            review=None,
            review_status="unavailable",
            review_unavailable_detail="not run in this test",
            recommendation="reject",
            recommendation_basis="No reviewer verdict was produced.",
        )

        pack_document = yaml.safe_load(PACK.read_text(encoding="utf-8"))
        command = packet.approval_command()

        assert _verdict(pack_document, command) == "blocked", (
            "the command the packet hands a human is exactly the one an agent is "
            "stopped from running; if the guard let it through, the handoff would "
            "be decoration"
        )
        assert OPERATOR_PLACEHOLDER in command, (
            "the rendered command carries placeholders where the human's own words "
            "belong, and those placeholders are refused when recorded verbatim"
        )
        assert _verdict(pack_document, packet.rejection_command()) == "allowed"


@pytest.mark.skipif(shutil.which("dcg") is None, reason="dcg is not installed here")
class TestAgainstTheShippedEngine:
    """The pack is a control only if the engine that loads it agrees with us."""

    def _dcg(self, command: str) -> str:
        completed = subprocess.run(
            ["dcg", "test", command],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
        )
        return completed.stdout + completed.stderr

    @pytest.mark.parametrize("command", BLOCKED)
    def test_dcg_blocks_adoption(self, command):
        assert "BLOCKED" in self._dcg(command), command

    @pytest.mark.parametrize("command", ALLOWED)
    def test_dcg_allows_preparation(self, command):
        assert "ALLOWED" in self._dcg(command), command
