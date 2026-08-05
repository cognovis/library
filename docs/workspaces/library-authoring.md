# Library Authoring Workspace

`library-platform:library-authoring` is a stable project baseline for repositories
that create or maintain Library primitives. Its direct roots are the five
platform-owned Forge Skills:

- `agent-forge`
- `skill-forge`
- `standard-forge`
- `script-forge`
- `hook-forge`

The Skills keep their factual operating Standards as ordinary `requires:`
dependencies. The Workspace does not contain `python-cli`, Pi extensions, Pi
profiles, Just modules, repository instructions, or customer-specific content.
A repository selects those capabilities independently when it needs them.

The Library platform therefore registers both `library-authoring` and
`cognovis-library-core:python-cli`. `cognovis-pi` registers only
`library-authoring`; its runtime primitives remain owned and versioned by the Pi
catalog.

Stable admission is backed by committed v2 Library locks in the Library platform
and `cognovis-pi`. Both consumers keep project install targets and harness bridges
relative, so repository relocation does not change Workspace intent. The Pi
consumer demonstrates the ownership boundary: the shared Forge capabilities come
from this Workspace while Pi extensions remain local to `cognovis-pi`.

Use a dry run before registration:

```text
library workspace use library-platform:library-authoring \
  --scope project --harness codex --dry-run --json
```

Then apply the same command without `--dry-run`. Existing direct roots are not
silently removed. After receipt verification, transfer equivalent direct intent
with the digest-bound `workspace adopt --from-direct` flow.
