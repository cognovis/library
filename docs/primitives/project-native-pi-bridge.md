# Project-Native Pi And Just Bridge

`pi-extension`, `pi-profile`, and `just-module` are temporary Library
primitives for harness-native files that the Open Skills format does not model.
They do not make the Library a second authority for skills or standards: Open
Skills remains the canonical reusable method layer.

All three primitives are project-only and have fixed destinations:

| Primitive | Destination |
|---|---|
| `pi-extension` file | `.agents/pi/extensions/NAME.SOURCE_EXTENSION` |
| `pi-extension` bundle | `.agents/pi/extensions/NAME/` plus optional project-local Pi package registration |
| `pi-profile` | `.agents/pi/profiles/NAME.SOURCE_EXTENSION` |
| `just-module` | `.agents/just/NAME.SOURCE_EXTENSION` |

The installer preserves a file's source extension or copies a complete extension
directory when `bundle: true`. Bundles declare a safe `entrypoint`, retain
relative imports and assets, and use a deterministic directory checksum.
Provenance is recorded in `.library.lock`; use, sync, audit, and remove share the
same lifecycle. Global scope, unsafe names, unsafe entrypoints, traversal, and
symlink escapes are rejected before artifact mutation.

A bundled extension that is an ordinary Pi package declares `pi_package: true`
in its catalog entry and provides `package.json` with a non-empty
`pi.extensions` manifest containing the catalog entrypoint. Library then merges
the bundle's relative path into the project-local `.pi/settings.json` `packages`
array. Relative package paths are written from the settings file's directory, as
Pi requires, so a target at `.agents/pi/extensions/solo-workbench` is registered
as `../.agents/pi/extensions/solo-workbench`. Existing settings and packages are
preserved, sync is idempotent, and remove deletes only the matching registration.
After project trust, plain `pi` loads the package; `pi list --approve` shows the
project-local registration.

For example, the complete Solo Workbench install is:

```bash
library pi-extension use solo-workbench --json
pi
```

No second `pi install` command is required. For an ad hoc checkout not managed
by Library, Pi's native equivalent remains:

```bash
pi install -l --approve ./.agents/pi/extensions/solo-workbench
```

Just is not the package-registration authority. A Just recipe may wrap the
Library command for operator convenience, but requiring Just for installation
would create a bootstrap dependency in projects without a root Justfile.
`just workbench` belongs to the separate ACPX clean-room workbench; the Solo
Workbench is loaded into an ordinary Pi session.

The repository owns its root `Justfile`. For `just-module` installs, Library
maintains only a managed import block and generated aggregator; hand-written
content remains repository-owned. A repository consumes all installed modules
through one stable optional import:

```just
set positional-arguments

import? '.agents/just/Justfile'
```

Library generates `.agents/just/Justfile` from installed `just-module` lock
entries after install, sync, or remove. `just --list` therefore reports the
commands currently installed in that repository.

The bridge should be retired when Pi and Just gain a canonical portable
distribution mechanism with equivalent project-local lifecycle and provenance
guarantees.
