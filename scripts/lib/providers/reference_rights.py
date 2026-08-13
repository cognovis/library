"""Recorded distribution rights for the ADR-0011 reference providers.

This module is **data, not policy**. It transcribes ADR-0011
`Resolved rights for the reference providers` so that the recorded state of a
real provider can be asserted rather than constructed in a test fixture. The
composition rules live in `providers.rights` and name no provider at all.

It sits beside the provider adapters for the same reason they do: naming a
provider is legitimate at the adapter boundary and nowhere else. The
provider-neutrality check treats this directory as the sanctioned location for
provider knowledge and scans the rights, admission, and executable-admission
gates as core.

Rights recorded here are the *researched* state, not a default. A provider that
is not listed resolves to nothing at all rather than to a permissive guess:
`rights_for` returns `None`, and the caller's own catalog configuration is then
the only source. An unlisted provider whose catalog entry records no rights
therefore lands on the all-`unknown` `Rights()` default, which blocks a
committed projection.
"""

from __future__ import annotations

from typing import Mapping

from .inventory import Rights

#: The Executive Circle MCP content provider. Recorded because it is the one
#: reference provider that exercises the rights-restricted path: a subscriber
#: token proves the endpoint will serve bytes and proves nothing else.
EXECUTIVE_CIRCLE_IDENTITY = "mcp:executive-circle"

#: The reference Git skills provider, MIT licensed.
SKILLS_REPO_IDENTITY = "https://github.com/mattpocock/skills"

#: The reference organization provider. Its grant is recorded **per repository**,
#: not organizationally: the same organization serves a repository with no
#: observed licence file, and it is not on the Library-owned allowlist. The
#: values below are the grant that holds for a repository whose licence *is*
#: observed; `normalize_inventory` relaxes the licence-derived grants to
#: `unknown` for any repository whose licence it cannot locate, which is what
#: keeps this entry from becoming an organization-wide grant by the back door.
ORGANIZATION_IDENTITY = "https://github.com/disler"

#: The Library-owned allowlist ADR-0011 records for the organization provider.
ORGANIZATION_ALLOWLIST = ("pi-vs-claude-code", "fusion-harness", "planf3")

_ORGANIZATION_MIT_EVIDENCE = (
    "per-repository MIT LICENSE recorded with commit pins in "
    "/Users/malte/code/library/cognovis-pi/docs/research/indydevdan-pi-repos.md, "
    "2026-08-08"
)

_MIT_EVIDENCE = (
    "upstream LICENSE (MIT) confirmed via raw.githubusercontent.com HTTP 200 and "
    "the repository API reporting spdx_id: MIT, 2026-08-08"
)

_SUBSCRIBER_EVIDENCE = (
    "subscriber-token-scoped MCP endpoint recorded in local harness configuration, "
    "2026-08-08"
)

_NO_GRANT_LOCATED = (
    "no published licence or redistribution grant located, 2026-08-08"
)

REFERENCE_PROVIDER_RIGHTS: Mapping[str, Rights] = {
    SKILLS_REPO_IDENTITY: Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source=_MIT_EVIDENCE,
    ),
    ORGANIZATION_IDENTITY: Rights(
        fetch_authorization="granted",
        install_rights="granted",
        redistribution_rights="granted",
        derivative_rights="granted",
        evidence_source=_ORGANIZATION_MIT_EVIDENCE,
    ),
    EXECUTIVE_CIRCLE_IDENTITY: Rights(
        fetch_authorization="granted",
        install_rights="unknown",
        redistribution_rights="unknown",
        derivative_rights="unknown",
        evidence_source=_NO_GRANT_LOCATED,
        grant_evidence={"fetch_authorization": _SUBSCRIBER_EVIDENCE},
    ),
}


def rights_for(provider_identity: str) -> Rights | None:
    """The recorded rights for one provider identity, or `None` when unlisted."""
    return REFERENCE_PROVIDER_RIGHTS.get(provider_identity)


def reference_rights_for(provider_identity: str) -> Rights:
    """The recorded rights for one reference provider.

    Raises:
        KeyError: when the provider is not one of the recorded reference
            providers. Callers that must tolerate an unlisted provider use
            `rights_for` and handle `None`; failing loudly here keeps a typo
            from silently reading as "no rights recorded".
    """
    try:
        return REFERENCE_PROVIDER_RIGHTS[provider_identity]
    except KeyError as exc:
        raise KeyError(
            f"no recorded reference rights for provider identity: {provider_identity}"
        ) from exc
