# Legacy projection inventory (ADR-0011, `CL-m6cc` AC5)

> **Generated. Do not edit.** Regenerate with
> `uv run python scripts/checks/legacy_projection_inventory.py`. The machine-readable
> form is `docs/reports/legacy-projection-inventory.json`; this document renders it.

This inventory replaces the name-matched survey in ADR-0011
`Legacy Projection Disposition`. Provenance here is derived **only** from a
normalized content digest matching a digest a provider actually served. A shared
name attributes nothing, and a Library-shaped bridge without a Library receipt is
not Library-owned.

A projection whose digest matches nothing is recorded
`rights-unresolved-pending-digest-attribution`. That is **non-compliant** in the
ADR's sense, which means exactly two things and no more:

- it may not be re-materialized by any later sync or repair, and
- it has an explicit remediation path an operator must choose.

It keeps every byte it has. Migration grants no deletion authority.


- Observed at: `2026-08-09T15:47:00Z`
- Roots: `/Users/malte/.claude/skills`, `/Users/malte/.claude/workflows`
- Foreign receipt stores read: none found
- Existing locks read for declared provenance: `/Users/malte/.config/library/global.lock`
- Resolved upstream digests available: 0

## Counts

| Measure | Count |
|---|---|
| `total` | 61 |
| `attributed` | 0 |
| `unattributed` | 38 |
| `receipted` | 23 |
| `unreceipted` | 38 |
| `compliant` | 23 |
| `non_compliant` | 38 |

## Entries

| Name | Kind | Members | Provenance | Redistribution | Receipt | Compliance | State |
|---|---|---|---|---|---|---|---|
| `acpx` | directory | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `acpx-dispatch` | symlink | 6 | receipt-declared | granted | receipted | compliant | - |
| `agent-forge` | symlink | 13 | receipt-declared | granted | receipted | compliant | - |
| `ask-matt` | symlink | 3 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `bead-context-pack.js` | file | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `bead-execution-loop` | symlink | 3 | receipt-declared | granted | receipted | compliant | - |
| `bead-implementation-loop` | symlink | 5 | receipt-declared | granted | receipted | compliant | - |
| `bead-review.js` | file | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `bead-reviewer` | symlink | 91 | receipt-declared | granted | receipted | compliant | - |
| `bug-triage` | symlink | 3 | receipt-declared | granted | receipted | compliant | - |
| `claude-handoff` | symlink | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `cmux` | symlink | 12 | receipt-declared | granted | receipted | compliant | - |
| `cmux-bead-dispatch` | symlink | 5 | receipt-declared | granted | receipted | compliant | - |
| `cmux-browser` | symlink | 11 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `cmux-workspace` | symlink | 5 | receipt-declared | granted | receipted | compliant | - |
| `code-review` | symlink | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `codebase-design` | directory | 4 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `codex-guide` | symlink | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `cognovis-beads` | symlink | 63 | receipt-declared | granted | receipted | compliant | - |
| `compound` | symlink | 2 | receipt-declared | granted | receipted | compliant | - |
| `council` | symlink | 6 | receipt-declared | granted | receipted | compliant | - |
| `diagnosing-bugs` | directory | 3 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `dolt` | symlink | 15 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `domain-modeling` | directory | 4 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `grill-me` | directory | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `grill-with-docs` | directory | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `grilling` | symlink | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `handoff` | directory | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `home-infra` | symlink | 5 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `hook-forge` | symlink | 14 | receipt-declared | granted | receipted | compliant | - |
| `implement` | directory | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `improve-codebase-architecture` | directory | 3 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `ingest-content` | symlink | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `inject-standards` | symlink | 2 | receipt-declared | granted | receipted | compliant | - |
| `intake` | symlink | 1 | receipt-declared | granted | receipted | compliant | - |
| `library` | symlink | 4468 | receipt-declared | granted | receipted | compliant | - |
| `loop-me` | symlink | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `mail-send` | symlink | 4 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `ob-triage` | symlink | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `parallelize` | symlink | 3 | receipt-declared | granted | receipted | compliant | - |
| `playwright-cli` | symlink | 11 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `prototype` | symlink | 4 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `quick-fix.js` | file | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `research` | directory | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `resolving-merge-conflicts` | directory | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `script-forge` | symlink | 2 | receipt-declared | granted | receipted | compliant | - |
| `session-close` | symlink | 1 | receipt-declared | granted | receipted | compliant | - |
| `setup-matt-pocock-skills` | symlink | 7 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `skill-forge` | symlink | 8 | receipt-declared | granted | receipted | compliant | - |
| `standard-forge` | symlink | 3 | receipt-declared | granted | receipted | compliant | - |
| `stream-review.js` | file | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `summarize` | symlink | 1 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `tdd` | symlink | 4 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `teach` | directory | 6 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `to-spec` | symlink | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `to-tickets` | directory | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `triage` | symlink | 4 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `wayfinder` | symlink | 2 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |
| `workplan` | symlink | 2 | receipt-declared | granted | receipted | compliant | - |
| `worktree-cleanup` | symlink | 4 | receipt-declared | granted | receipted | compliant | - |
| `writing-great-skills` | directory | 3 | unattributed | unknown | unreceipted | non-compliant | rights-unresolved-pending-digest-attribution |

## Digests

| Name | Path | Normalized content digest | Link target |
|---|---|---|---|
| `acpx` | `/Users/malte/.claude/skills/acpx` | `sha256:8a9b8bd62f502a168d7cf3e7b24137c15d2cec5e1a60a723e1948ecf5475bce6` | - |
| `acpx-dispatch` | `/Users/malte/.claude/skills/acpx-dispatch` | `sha256:262450c082cc76c1f73347d23c60c6028f482e003725153b05d7af1681c95dbf` | `/Users/malte/.agents/skills/acpx-dispatch` |
| `agent-forge` | `/Users/malte/.claude/skills/agent-forge` | `sha256:949e9677a82c34ec0ae3910b8c4715d222a6914fc51ce2cc0a1928553aac1667` | `/Users/malte/.local/share/library/skills/unknown/agent-forge@73bd8175f04360` |
| `ask-matt` | `/Users/malte/.claude/skills/ask-matt` | `sha256:90c3ec8eb50a368a2f9502ad5511345c753b9aaf6d84a9aa2e763d2ce5374f50` | `../../.agents/skills/ask-matt` |
| `bead-context-pack.js` | `/Users/malte/.claude/workflows/bead-context-pack.js` | `sha256:a1e9e78d43acb67a68f105ebdcc0dc764030333147fce449ba4b55bbcc90dea7` | - |
| `bead-execution-loop` | `/Users/malte/.claude/skills/bead-execution-loop` | `sha256:433e801a0e116e62249dae9274776f31451a7df65aead68af375e706ff7d617b` | `/Users/malte/.agents/skills/bead-execution-loop` |
| `bead-implementation-loop` | `/Users/malte/.claude/skills/bead-implementation-loop` | `sha256:142f608def827a965d788fcf00acd9c6061295d219e645a9efa4cfb9ace719a0` | `/Users/malte/.agents/skills/bead-implementation-loop` |
| `bead-review.js` | `/Users/malte/.claude/workflows/bead-review.js` | `sha256:1a2343aab94b0f226bb6a0513ef73ae92d9ebd5e7707b1835ce171a343ef234f` | - |
| `bead-reviewer` | `/Users/malte/.claude/skills/bead-reviewer` | `sha256:b1c690f6f3f9db5d694890cbb1360f7c5ed8be06f8228714e6da71722300bdcc` | `/Users/malte/.agents/skills/bead-reviewer` |
| `bug-triage` | `/Users/malte/.claude/skills/bug-triage` | `sha256:f7c0cbf87147e0eba1c6cb4dce50e9bfb428e7ba3974f9926953e126e6f02525` | `/Users/malte/.agents/skills/bug-triage` |
| `claude-handoff` | `/Users/malte/.claude/skills/claude-handoff` | `sha256:fead75b532cbb75312e3bbe0dad759251876e03a7207efa6abfe77e8b6c92345` | `../../.agents/skills/claude-handoff` |
| `cmux` | `/Users/malte/.claude/skills/cmux` | `sha256:c94f1b49fbcac3ea2361288d8a52504b5255e1c57a8073c32862eb1b7d292877` | `/Users/malte/.agents/skills/cmux` |
| `cmux-bead-dispatch` | `/Users/malte/.claude/skills/cmux-bead-dispatch` | `sha256:8957e4e1fad28435729ec117d32dfc9437dccb588916ef0ea3ad7335053e01e8` | `/Users/malte/.agents/skills/cmux-bead-dispatch` |
| `cmux-browser` | `/Users/malte/.claude/skills/cmux-browser` | `sha256:7322e884d9cb768db04473f92daaac18eeec8fd501dd427fd1875944d8deea34` | `/Users/malte/.agents/skills/cmux-browser` |
| `cmux-workspace` | `/Users/malte/.claude/skills/cmux-workspace` | `sha256:457896610ab5e097736b6e0b95ef09775f2bca35a2074c096aeedee2a0edad9b` | `/Users/malte/.agents/skills/cmux-workspace` |
| `code-review` | `/Users/malte/.claude/skills/code-review` | `sha256:0430dedd8b6cbf25322cab71411b0ec1a3d7248f013597f5c1bb7efff35b5d52` | `../../.agents/skills/code-review` |
| `codebase-design` | `/Users/malte/.claude/skills/codebase-design` | `sha256:7b4d58a410b594ba4c4c1514c504631e1f0945fa1f290bfc27f128a364984a90` | - |
| `codex-guide` | `/Users/malte/.claude/skills/codex-guide` | `sha256:2d55295fa6b619d27616fdd6a647e68a04ab1163e4441112efb374533cefa50a` | `/Users/malte/.agents/skills/codex-guide` |
| `cognovis-beads` | `/Users/malte/.claude/skills/cognovis-beads` | `sha256:534aba359d5ac8e299a54f977edd64410fbea3414b0da25d855d8f7a7f17914d` | `/Users/malte/.agents/skills/cognovis-beads` |
| `compound` | `/Users/malte/.claude/skills/compound` | `sha256:069b927514495e19db3145e90bbc3e2f2b364694f1e974d612b30332caa14fcc` | `/Users/malte/.agents/skills/compound` |
| `council` | `/Users/malte/.claude/skills/council` | `sha256:30ff343ef6369e751bc5930154c26277fd74f54d75dc11ce9dbfcf1b20b8f46b` | `/Users/malte/.agents/skills/council` |
| `diagnosing-bugs` | `/Users/malte/.claude/skills/diagnosing-bugs` | `sha256:b266f01aa2b56e38c238a183e8d595ea03e3931a082023a3926ca83b43ad287a` | - |
| `dolt` | `/Users/malte/.claude/skills/dolt` | `sha256:48d890028d4c636a77188c9fb3bf3c6738efe17a69731e6559e9dd7ef6f00d56` | `/Users/malte/.agents/skills/dolt` |
| `domain-modeling` | `/Users/malte/.claude/skills/domain-modeling` | `sha256:d6f18e3ecc5a6cb5cc1033cece8f4e767883fbe19284ac61cb4d201c660ddeba` | - |
| `grill-me` | `/Users/malte/.claude/skills/grill-me` | `sha256:b52b7488898c14e6158abe240acf004f49552bc31c5a1192f479b6da4873ae53` | - |
| `grill-with-docs` | `/Users/malte/.claude/skills/grill-with-docs` | `sha256:a50d75cfbf97e1ce71345e7a7e34faf83352f34435a54447aaa87a5b4c0e66f0` | - |
| `grilling` | `/Users/malte/.claude/skills/grilling` | `sha256:7139003034b14410ee75bb2f35a3f4dbcddce3ce1a541a9c9b4ce245906ec0e5` | `../../.agents/skills/grilling` |
| `handoff` | `/Users/malte/.claude/skills/handoff` | `sha256:d52b621d0ed044ae6857aa61769cf104b978450d6dfa5ebc582943225a41492b` | - |
| `home-infra` | `/Users/malte/.claude/skills/home-infra` | `sha256:3e5ae27f38b58bbd64ba864ce2620d88e6e603280f31a35102a5ee7fe8090390` | `/Users/malte/.agents/skills/home-infra` |
| `hook-forge` | `/Users/malte/.claude/skills/hook-forge` | `sha256:44e8f2cd04d23677567ea0a395a3ac4880e24cf0d7d7ff54fd058997db9b3d42` | `/Users/malte/.local/share/library/skills/unknown/hook-forge@73bd8175f04360` |
| `implement` | `/Users/malte/.claude/skills/implement` | `sha256:c9237ae8daed621ffab3f248c477a14636cde70e2efa81cb9afb4c99132b84c6` | - |
| `improve-codebase-architecture` | `/Users/malte/.claude/skills/improve-codebase-architecture` | `sha256:491bd690d3075f99161493b6bfcd12f10bba758b66117f8b12bfc73ceea6539a` | - |
| `ingest-content` | `/Users/malte/.claude/skills/ingest-content` | `sha256:fa021b2f6f8ef55b7d1dfb8420a42060f24b59771488e4fb6efd2d7ee74315ec` | `/Users/malte/.agents/skills/ingest-content` |
| `inject-standards` | `/Users/malte/.claude/skills/inject-standards` | `sha256:ec8a7dd74e22e030b2d12ec45242635da9a0b4baeacd4407688dd6ef710fee49` | `/Users/malte/.agents/skills/inject-standards` |
| `intake` | `/Users/malte/.claude/skills/intake` | `sha256:58e4d981570e24d153e88e991e04a0ec6c91db3ee701ab83f70ce21b570dca55` | `/Users/malte/.agents/skills/intake` |
| `library` | `/Users/malte/.claude/skills/library` | `sha256:c5fe3c0f4bd4f0770ee8ed29038ba44823355c4acaccdfb54feaffa49f9976c5` | `/Users/malte/code/library/meta` |
| `loop-me` | `/Users/malte/.claude/skills/loop-me` | `sha256:e499fb213ab08b83c291f8deff2428af148a39ea12f9fb5b03a309a53591430d` | `../../.agents/skills/loop-me` |
| `mail-send` | `/Users/malte/.claude/skills/mail-send` | `sha256:b44d796115ca23c71e4f96efbcdf9cf15ec20bee01ac65b37eaa1c5fcf51df1b` | `/Users/malte/.agents/skills/mail-send` |
| `ob-triage` | `/Users/malte/.claude/skills/ob-triage` | `sha256:54362babb77cce7d2687d6cb9008f1369bc79c00e80a8790d91ba726146129ca` | `/Users/malte/.agents/skills/ob-triage` |
| `parallelize` | `/Users/malte/.claude/skills/parallelize` | `sha256:3c0b62b4d4724bf7c312ce4bf43fe882543f13621591da9db93cc474d70b3c66` | `/Users/malte/.agents/skills/parallelize` |
| `playwright-cli` | `/Users/malte/.claude/skills/playwright-cli` | `sha256:a8ac88570d81a2e7dd0314dc66931e7ed023769dd539a8265c338e32677362ca` | `/Users/malte/.agents/skills/playwright-cli` |
| `prototype` | `/Users/malte/.claude/skills/prototype` | `sha256:6d66eaf594de7346fbca970a7ab7aa68ce6be071cb2eea1e438b4377c51cec52` | `../../.agents/skills/prototype` |
| `quick-fix.js` | `/Users/malte/.claude/workflows/quick-fix.js` | `sha256:4549808d23fb440add1b9b794a4fb4de201a09c45833d203aed47ab5b0cce94d` | - |
| `research` | `/Users/malte/.claude/skills/research` | `sha256:01ebe84c029851721c7485d4fada58fd4f55dc2966507401b8e5ba9295eb3289` | - |
| `resolving-merge-conflicts` | `/Users/malte/.claude/skills/resolving-merge-conflicts` | `sha256:51034ea108bea3783ed6b8002b3bf02c718d906380358aea9bb708576840b058` | - |
| `script-forge` | `/Users/malte/.claude/skills/script-forge` | `sha256:8177dc31051014251c1a401f9437982a00194db702dd945b97d3b74dd3f8011e` | `/Users/malte/.local/share/library/skills/unknown/script-forge@73bd8175f04360` |
| `session-close` | `/Users/malte/.claude/skills/session-close` | `sha256:3d1a21c26ee0240d89b9d7ce0dc7e7dea66fbd98c2d6dc2bd5d15d27dad37614` | `/Users/malte/.agents/skills/session-close` |
| `setup-matt-pocock-skills` | `/Users/malte/.claude/skills/setup-matt-pocock-skills` | `sha256:b7b7eb4d7df59ca7ff1b91e0fd9ccbaf309f25ef4ae5a0eb7598fff031564763` | `../../.agents/skills/setup-matt-pocock-skills` |
| `skill-forge` | `/Users/malte/.claude/skills/skill-forge` | `sha256:8cc1272837e1c545c2b0ef1ad49b97354c2f1f05ba180501404202914fa396b8` | `/Users/malte/.local/share/library/skills/unknown/skill-forge@73bd8175f04360` |
| `standard-forge` | `/Users/malte/.claude/skills/standard-forge` | `sha256:9dee4d38838758bc206266d4cc797d98ca2a060641a4d703f864edc4d56f115f` | `/Users/malte/.local/share/library/skills/unknown/standard-forge@73bd8175f04360` |
| `stream-review.js` | `/Users/malte/.claude/workflows/stream-review.js` | `sha256:5a3278c8b6cce305fa2fe170908d22dcd23102a5a9f9e27813d78c615f039872` | - |
| `summarize` | `/Users/malte/.claude/skills/summarize` | `sha256:d3a784e658396ffde94dbcf3d0682d728b9d8dcb4c5631390dd77f942adb76f8` | `/Users/malte/.agents/skills/summarize` |
| `tdd` | `/Users/malte/.claude/skills/tdd` | `sha256:728b7b7df6b255d9593af33045f4154f50ad99da8716e3ccba0be7788b015524` | `../../.agents/skills/tdd` |
| `teach` | `/Users/malte/.claude/skills/teach` | `sha256:7e6b30c8bfc7ba922face0e81a2e966fb334c108000ee5adc365fecc2161b628` | - |
| `to-spec` | `/Users/malte/.claude/skills/to-spec` | `sha256:fedf7e6e592506cbf93b08d71912bb652ff1c69eb1db6ac35674deb79fe4d81b` | `../../.agents/skills/to-spec` |
| `to-tickets` | `/Users/malte/.claude/skills/to-tickets` | `sha256:2906e775aa38b32f29da3817ccd168911194adedd9db4a2917414ff20193ac78` | - |
| `triage` | `/Users/malte/.claude/skills/triage` | `sha256:4ceaf0612fc6965f369ff69eb3493b87769de7c7b7fa2cafa0fc92d22ee89e61` | `../../.agents/skills/triage` |
| `wayfinder` | `/Users/malte/.claude/skills/wayfinder` | `sha256:618fc281e0388482485b43b2211e9f2003d62a670aad0259dc5c1cf0c5225c51` | `../../.agents/skills/wayfinder` |
| `workplan` | `/Users/malte/.claude/skills/workplan` | `sha256:cb69b1f916662e998dd8200bac7560fbfc8b0584d0d7d79c67a5382c63a014b4` | `/Users/malte/.agents/skills/workplan` |
| `worktree-cleanup` | `/Users/malte/.claude/skills/worktree-cleanup` | `sha256:7645d89baf64493b644e1ef20977b6fd89f75250fea417d06d344913723b6f40` | `/Users/malte/.agents/skills/worktree-cleanup` |
| `writing-great-skills` | `/Users/malte/.claude/skills/writing-great-skills` | `sha256:5a3d3bed31dc6e5778900452b9d579f15f26950ba6f32b16a359c5e35da38878` | - |

## Remediation

Every non-compliant entry above carries both ADR-0011 remediation paths: `operator-confirmed-removal` and `relocate-machine-local`. Neither runs automatically. `scripts/lib/providers/legacy_projections.py` issues the statement and accepts only a confirmation bound to that statement, so a remediation cannot happen without the operator having been shown what it affects.
