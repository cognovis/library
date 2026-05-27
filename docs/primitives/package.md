# Package

> Primitive reference extracted from [PRIMITIVES.md](../PRIMITIVES.md).
>
> Previously named "Plugin". Renamed 2026-05-27 to align with Pi
> (`pi install`, `pi.dev/packages`) and npm/git native distribution
> semantics. Structural surfaces (`library.yaml` keys, installer CLI) may
> still use "plugin" — that rename is tracked separately.

**Definition.** An installable unit that bundles multiple primitives (skills,
commands, agents, hooks, workflows) into a single versioned package distributed
from one source. (Scripts are a deterministic primitive, but they are not
model-invoked by themselves; see Script below.)

**Key constitutive feature.** Composite installable: a package is defined by its
bundling — it contains multiple primitive types that work together as a coherent
capability. Installing a package installs all its parts atomically.

**Trigger semantics.** Packages are not directly invoked. A user (or CI) runs
`/install-package <name>` (`pi install <source>`, `/library use <name>`) to
install. After installation, each bundled primitive activates according to its
own trigger semantics.

**Cost.** Package cost = sum of costs of all bundled primitives. Evaluate each
bundled skill/hook for its standing context or latency cost.

**When to choose it.** Use a package when:
- A capability requires multiple cooperating primitives (e.g., a skill + a hook that
  enforces its use).
- You want atomic distribution: if the skill is installed without its companion hook,
  the capability is broken.
- You are publishing to a marketplace for others to discover and install.

**Counter-examples.**
- Do NOT create a package for a single skill — that is over-packaging.
- Do NOT treat a package as a primitive you can invoke — install it first, then invoke
  its constituent primitives normally.

**Worked examples.**

| Package | Why it is a package |
|---------|---------------------|
| `reference-file-compactor` | Bundles a skill + a command + hooks into one installable. The skill alone would not work without the companion hooks; atomicity is required. |
| `beads-workflow` | Bundles multiple agents + hooks (with internal scripts as implementation detail of each). The bead orchestration workflow only works when all parts are co-installed. |

---
