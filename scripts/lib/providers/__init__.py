"""Source-provider capability contract and normalized inventory core.

ADR-0011 (`docs/adr/heterogeneous-marketplace-workspaces.md`) replaces the
"one universal scanner" model with a declared capability contract. A provider
adapter answers `capabilities()`; the resolver, cache, and Workspace layers
consume the normalized inventory only, and contain no provider-specific branch.

Module map:

| Module | Owns |
|---|---|
| `contract` | The adapter capability contract and its typed value objects |
| `inventory` | The normalized item schema, qualified identity, and the index |
| `normalize` | Provider output -> normalized inventory, driven by `capabilities()` |
| `git_repo` | The reference `git-repo` adapter (remote-only, no local checkout) |
| `registration` | Provider registration, which installs nothing |

This package deliberately exports nothing at package level. Importing the
adapter modules eagerly here would make every consumer of the normalized item
schema import a provider adapter, which is the coupling the whole contract
exists to prevent. Import the module you need.
"""

from __future__ import annotations
