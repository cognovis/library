"""The operator decision a foreign install needs, for tests that are about something else.

`CL-lt51` amended ADR-0011 Invariant 12: model-instructing content from a foreign
steward -- a Skill, a Prompt, a Standard, an Agent -- requires the same
digest-bound admission decision an executable does, because an agent harness
loads it into a model's context precisely so the model will follow it.

Most suites that install foreign content are not about that gate. They are about
the cache transaction, retention, purge, offline semantics, or one provider
adapter, and they install a Skill because a Skill is the ordinary thing a
marketplace serves. Those suites now have to supply the decision their content
needs.

This helper does **not** admit everything. It records a decision about the exact
bytes the caller is about to install, so an install of different bytes still
fails the gate and a test that stops digesting what it materializes still breaks.
The alternative -- an authority that answers `admitted` to any question -- would
have turned every one of those suites into a place where a real regression in the
gate goes unnoticed.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from lib.providers.classification import FOREIGN, requires_admission
from lib.providers.executable_admission import (
    ExecutableAdmissionLedger,
    content_digest,
)

#: What these fixtures record as the deciding operator. A test ledger is still a
#: ledger: the record carries an identity and a stated reason, because
#: `AdmissionRecord` refuses one that does not.
TEST_OPERATOR = "malte.sussdorff@cognovis.de"
TEST_REASON = (
    "test fixture: read this item's complete body and recorded the decision the "
    "install path requires for these exact bytes"
)
TEST_DECIDED_AT = "2026-08-10T09:00:00Z"


def admitting_ledger(
    entries: Mapping[str, tuple[Mapping[str, bytes], str]],
) -> ExecutableAdmissionLedger:
    """A ledger admitting exactly the given `(identity -> (files, type))` pairs."""
    ledger = ExecutableAdmissionLedger()
    for identity, (files, library_type) in entries.items():
        ledger.admit(
            identity,
            content_digest(files),
            library_type=library_type,
            reviewer=TEST_OPERATOR,
            permission_surface=(),
            decided_at=TEST_DECIDED_AT,
            evidence=TEST_REASON,
        )
    return ledger


def admitting(
    identity: str,
    files: Mapping[str, bytes],
    library_type: str = "skill",
) -> ExecutableAdmissionLedger:
    """A ledger admitting exactly one item's exact bytes."""
    return admitting_ledger({identity: (dict(files), library_type)})


def stand_in_contents(inventory: Iterable[Any]) -> dict[str, dict[str, bytes]]:
    """One distinct byte payload per item, for evaluating a whole inventory.

    Discovery does not fetch whole items, so an inventory evaluated at discovery
    time has no content to digest and every admission-requiring item is
    `pending`. A test that wants to see *past* that axis -- to check that rights
    or maturity is what separates two items -- has to supply content and a
    decision about it. These payloads stand in for the real upstream bytes; what
    they prove is which axis moved, not what the upstream says.
    """
    return {
        item.qualified_identity(): {"content": item.qualified_identity().encode("utf-8")}
        for item in inventory
    }


def admitting_inventory(inventory: Iterable[Any]) -> ExecutableAdmissionLedger:
    """A decision for every admission-requiring item, over `stand_in_contents`."""
    contents = stand_in_contents(inventory)
    return admitting_ledger(
        {
            item.qualified_identity(): (
                contents[item.qualified_identity()],
                item.library_type,
            )
            for item in inventory
            if requires_admission(item.library_type, FOREIGN)
        }
    )
