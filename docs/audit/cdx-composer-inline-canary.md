# CDX Composer Inline Cursor Dispatch Canary

Bead: `CL-7p1j`
Purpose: Harmless documentation-only canary for CL-8832 live verification. The
`cdx-composer` quick path should reach the real `cursor-impl.py` adapter and emit
`LEAF_DISPATCH` plus `CURSOR_AGENT_START adapter=cursor-impl` markers.

## Result

Inline Cursor Composer leaf dispatch completed this doc-only change without
runtime code edits.

Parent verification: `CL-8832`

## Canary Token

`CDX_COMPOSER_INLINE_CANARY_OK`
