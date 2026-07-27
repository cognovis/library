# Project-Native Pi And Just Bridge

`pi-extension`, `pi-profile`, and `just-module` are temporary Library
primitives for harness-native files that the Open Skills format does not model.
They do not make the Library a second authority for skills or standards: Open
Skills remains the canonical reusable method layer.

All three primitives are project-only and have fixed destinations:

| Primitive | Destination |
|---|---|
| `pi-extension` file | `.agents/pi/extensions/NAME.SOURCE_EXTENSION` |
| `pi-extension` bundle | `.agents/pi/extensions/NAME/` |
| `pi-profile` | `.agents/pi/profiles/NAME.SOURCE_EXTENSION` |
| `just-module` | `.agents/just/NAME.SOURCE_EXTENSION` |

The installer preserves a file's source extension or copies a complete extension
directory when `bundle: true`. Bundles declare a safe `entrypoint`, retain
relative imports and assets, and use a deterministic directory checksum.
Provenance is recorded in `.library.lock`; use, sync, audit, and remove share the
same lifecycle. Global scope, unsafe names, unsafe entrypoints, traversal, and
symlink escapes are rejected before artifact mutation.

The repository owns its root `Justfile`. Library installation never creates or
changes it. A repository consumes all installed modules through one stable
optional import:

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
