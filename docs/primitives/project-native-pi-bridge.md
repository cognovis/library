# Project-Native Pi And Just Bridge

`pi-extension`, `pi-profile`, and `just-module` are temporary Library
primitives for harness-native files that the Open Skills format does not model.
They do not make the Library a second authority for skills or standards: Open
Skills remains the canonical reusable method layer.

All three primitives are project-only and have fixed destinations:

| Primitive | Destination |
|---|---|
| `pi-extension` | `.agents/pi/extensions/NAME.SOURCE_EXTENSION` |
| `pi-profile` | `.agents/pi/profiles/NAME.SOURCE_EXTENSION` |
| `just-module` | `.agents/just/NAME.SOURCE_EXTENSION` |

The installer preserves the source extension, records provenance and checksum
in `.library.lock`, resolves typed dependencies, and supports use, sync, audit,
and remove. Global scope and names containing path traversal are rejected before
any dependency or filesystem mutation.

The repository owns its root `Justfile`. Library installation never creates or
changes it. A repository may explicitly consume an installed module:

```just
import '.agents/just/pi-workbench.just'
```

The bridge should be retired when Pi and Just gain a canonical portable
distribution mechanism with equivalent project-local lifecycle and provenance
guarantees.
