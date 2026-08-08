Task tracking lives in beads (`bd`). Issue state, priority and history are authoritative there — never open a parallel tracker in markdown checklists, TODO comments or summary files, and refer to work by its bead id.

Durable project memory lives in open-brain (`ob`). Decisions, prior work and context older than this session are recorded there rather than in the repository, so treat it as the place to look before concluding that something has no history.

In Fusion, the CLI names above identify the backing systems, not the required invocation. Use `beads_read` for read-only Beads access and the available `mcp__open-brain__*` tools for read-only Open Brain access. These tools do not require Bash: do not mistake missing shell access for missing project task or memory context. Consult them when the request materially depends on issue state, history, prior decisions or earlier work. Report a context source as unavailable only if its dedicated tool is absent or fails.

Ground every statement about the codebase in what you actually read, and cite `file:line`. Where you could not verify something, say so plainly instead of presenting it as established.

Code, comments, identifiers and log messages are English. No emoji in source, config or technical documentation.

Report what you did and what you did not do. Do not describe work as complete unless it is, and do not claim a check passed unless you ran it.
