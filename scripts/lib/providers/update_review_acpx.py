"""The review stage's transport: one agent-shell dispatch per update packet.

`update_admission` takes a `ReviewDispatch` callable and never learns what is
behind it. This module is the shipped one, and it is deliberately thin: it builds
a command, runs it, reads the answer, and extracts one typed verdict. It chooses
no model, writes no prompt, and interprets no verdict -- the prompt comes from
`update_admission.review_prompt`, the model and adapter come from the caller or
the recorded defaults, and the verdict is validated against the change-set digest
by `update_admission.validated_review_verdict`.

**Every failure here is `ReviewUnavailable`, and that is the point.** A missing
dispatcher, an unconfigured route, a provider content filter, a timeout, an
answer with no JSON object in it: none of them is a passing review, and none of
them may be handled by proceeding. `prepare_update` turns the exception into
`review_status: unavailable` and a `reject` recommendation, so the operator is
told the reviewer did not answer rather than shown a packet that looks reviewed.

**Credentials are out of scope, deliberately.** If the configured adapter has no
route for the requested model, this module reports that and stops. Adding a
provider entry or a credential is a human security act and is held behind a human
review, exactly as `CL-n7ex` left operator identity.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from .update_admission import (
    REVIEW_VERDICT_SCHEMA,
    ChangeSet,
    ReviewUnavailable,
    ReviewVerdict,
)

#: Where the agent-shell gateway lives when it is installed. Looked up rather
#: than vendored: the dispatcher owns session preparation, output extraction,
#: telemetry, and the approve-all worktree confinement, and a second copy of that
#: contract in this repository would be a second place for it to drift.
DEFAULT_DISPATCH_SCRIPT = Path.home() / ".claude" / "skills" / "acpx-dispatch" / "scripts" / "acpx-dispatch.py"

#: The recorded default route for an update review. A caller may override both.
#: This is a *default*, not a policy: model routing is owned by the caller and by
#: `dispatch/model-routing`, and naming one here only avoids a required argument
#: for the ordinary case.
DEFAULT_AGENT = "codex"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING = "high"

#: The permission value an update review runs under: **no tools at all**.
#:
#: Wave-1 review found the first version of this module dispatching with
#: `approve-reads` inside the repository worktree, and that is the exact failure
#: this bead exists to prevent, one layer up. The prompt embeds the complete
#: content of a foreign item that nobody has admitted yet, and that content's
#: entire threat model is that a model follows it. A reviewer holding read
#: capability can therefore be instructed by the artifact under review to read
#: `~/.ssh/id_rsa` and put it in its summary -- and the summary is written into a
#: packet a human then reads.
#:
#: The reviewer needs no capability: the whole item is already in its prompt.
#: This is the capability isolation `~/.agents/standards/security/content-isolation`
#: describes -- a powerless context that returns a structured answer -- and it is
#: a blast-radius control, not an injection detector.
REVIEW_PERMISSIONS = "deny-all"

#: The directory the review runs in. Never the repository: a denied tool call is
#: the control, and a working directory that contains nothing worth reading is
#: the belt beside it.
ISOLATED_WORKSPACE_NAME = "review-workspace"

#: Stable telemetry caller id.
CALLER = "library-marketplace-update-review"

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _extract_verdict(answer: str) -> dict[str, Any]:
    """The one verdict object in a model's answer, or a refusal.

    Models wrap JSON in prose and in fenced blocks. What this must not do is
    accept the *first* brace-delimited run it finds and hope: an answer that
    discusses a JSON shape before emitting one would yield the example rather
    than the verdict. It therefore looks for the object carrying this module's
    schema, and refuses when there is not exactly one.
    """
    candidates: list[dict[str, Any]] = []
    for block in re.findall(r"```(?:json)?\s*(.*?)```", answer, re.DOTALL) or []:
        try:
            parsed = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema") == REVIEW_VERDICT_SCHEMA:
            candidates.append(parsed)
    if not candidates:
        match = _JSON_OBJECT.search(answer)
        if match is not None:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("schema") == REVIEW_VERDICT_SCHEMA:
                candidates.append(parsed)
    if len(candidates) != 1:
        raise ReviewUnavailable(
            "the reviewer's answer does not contain exactly one "
            f"{REVIEW_VERDICT_SCHEMA} object ({len(candidates)} found), so no "
            "verdict was recorded"
        )
    return candidates[0]


def acpx_review(
    *,
    artifacts: Path,
    agent: str = DEFAULT_AGENT,
    model: str = DEFAULT_MODEL,
    reasoning: str = DEFAULT_REASONING,
    session: str | None = None,
    dispatch_script: Path | None = None,
    timeout_seconds: int = 900,
    runner=subprocess.run,
):
    """A `ReviewDispatch` that asks one powerless reviewer about one change set.

    Args:
        artifacts: Where this dispatch's event and answer files are written. Each
            invocation allocates fresh paths under it; a reused path would let a
            retry overwrite the evidence of the attempt it is retrying. The
            reviewer's own empty working directory is created beside them.

    There is deliberately **no `workspace` argument**. The caller does not get to
    choose where a reviewer of unadmitted foreign instructions runs, because the
    one choice that matters -- "somewhere with nothing in it" -- is the control.

    Returns:
        A callable suitable as `prepare_update(review=...)`.
    """
    script = Path(dispatch_script) if dispatch_script is not None else DEFAULT_DISPATCH_SCRIPT

    def dispatch(change_set: ChangeSet, prompt_path: Path) -> ReviewVerdict:
        if not script.is_file():
            raise ReviewUnavailable(
                f"the agent-shell dispatcher is not installed at {script}; install "
                "the acpx-dispatch skill or pass an explicit dispatch_script"
            )
        if shutil.which("uv") is None:
            raise ReviewUnavailable("uv is not on PATH, so the dispatcher cannot be run")
        artifacts.mkdir(parents=True, exist_ok=True)
        attempt = uuid.uuid4().hex[:12]
        events = artifacts / f"update-review-{attempt}.events.ndjson"
        answer = artifacts / f"update-review-{attempt}.answer.md"
        workspace = artifacts / ISOLATED_WORKSPACE_NAME / attempt
        workspace.mkdir(parents=True, exist_ok=True)
        command: Sequence[str] = [
            "uv",
            "run",
            "python",
            str(script),
            "run",
            "--agent",
            agent,
            "--model",
            model,
            "--reasoning",
            reasoning,
            "--session",
            session or f"library-update-review-{change_set.digest()[7:19]}",
            "--cwd",
            str(workspace),
            "--caller",
            CALLER,
            "--prompt-file",
            str(prompt_path),
            "--permissions",
            REVIEW_PERMISSIONS,
            "--events-file",
            str(events),
            "--answer-file",
            str(answer),
        ]
        try:
            completed = runner(
                list(command),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(workspace),
                env=dict(os.environ),
            )
        except subprocess.TimeoutExpired as exc:
            raise ReviewUnavailable(
                f"the reviewer did not answer within {timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise ReviewUnavailable(f"the dispatcher could not be started: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise ReviewUnavailable(
                "the review dispatch failed: "
                + (detail[-1] if detail else f"exit code {completed.returncode}")
            )
        if not answer.is_file():
            raise ReviewUnavailable(
                "the dispatch reported success and wrote no answer file; an idle "
                "session is not a completed review"
            )
        payload = _extract_verdict(answer.read_text(encoding="utf-8"))
        try:
            return ReviewVerdict.from_dict(payload)
        except (KeyError, ValueError) as exc:
            raise ReviewUnavailable(
                f"the reviewer's verdict is malformed and was not recorded: {exc}"
            ) from exc

    return dispatch


def recorded_review(verdict: Mapping[str, Any]):
    """A `ReviewDispatch` that replays one already-recorded verdict.

    For an operator who ran the review by hand and holds its artifact. It is not
    a way around the review stage: the verdict still has to name this change set,
    and `validated_review_verdict` refuses it otherwise.
    """

    def dispatch(change_set: ChangeSet, prompt_path: Path) -> ReviewVerdict:
        return ReviewVerdict.from_dict(verdict)

    return dispatch


__all__ = [
    "ISOLATED_WORKSPACE_NAME",
    "CALLER",
    "DEFAULT_AGENT",
    "DEFAULT_DISPATCH_SCRIPT",
    "DEFAULT_MODEL",
    "DEFAULT_REASONING",
    "REVIEW_PERMISSIONS",
    "acpx_review",
    "recorded_review",
]
