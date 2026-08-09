#!/usr/bin/env python3
"""Rebuild the `git-org` reference capture from local checkouts.

The capture mirrors the host Git data API responses the `git-org` adapter reads,
and every value in it is derived from a **real repository at the exact commit
ADR-0011 and `indydevdan-pi-repos.md` pin**: the tree listing is `git ls-tree`,
the blob identity is the object's own Git sha, and the recorded bytes are the
file's bytes. Nothing here is invented, which is the point -- a hand-written
organization fixture would let the adapter pass against a shape no host serves.

`tests/test_provider_disler.py::test_capture_matches_live_organization` re-checks
the repository listing and the per-repository commits against the live provider
when `NETWORK_TESTS=1`, so the offline evidence stays bound to reality.

Usage:
    uv run python tests/fixtures/provider_git_org/build_capture.py \\
        --checkouts /Users/malte/code/learning-references/indydevdan
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

ORGANIZATION = "disler"
API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"

#: Every repository the organization serves that this capture records. The
#: allowlist is a separate, Library-owned decision; the listing is upstream's.
SERVED = (
    "pi-vs-claude-code",
    "fusion-harness",
    "planf3",
    "live-bench",
)

#: Blob bytes worth recording: the members the tests actually fetch. A capture
#: of every file would be a repository copy wearing a fixture's name.
RECORDED_BYTES_PREFIXES = {
    "planf3": (".claude/skills/planf3/", "prompts/", "specs/pi-iroh-coms-net.html"),
}


def _run(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return result.stdout


def build(checkouts: Path) -> dict[str, object]:
    listing = [{"name": name} for name in SERVED]
    payload: dict[str, object] = {}
    blobs: dict[str, str] = {}
    commits: dict[str, str] = {}

    payload[f"{API_BASE}/users/{ORGANIZATION}/repos?per_page=100"] = listing

    for name in SERVED:
        repo = checkouts / name
        commit = _run(repo, "rev-parse", "HEAD").strip()
        commits[name] = commit
        payload[f"{API_BASE}/repos/{ORGANIZATION}/{name}/git/ref/heads/main"] = {
            "object": {"sha": commit}
        }
        entries = []
        for line in _run(repo, "ls-tree", "-r", commit).splitlines():
            meta, path = line.split("\t", 1)
            mode, kind, sha = meta.split()
            if kind != "blob":
                continue
            entries.append({"path": path, "type": "blob", "sha": sha, "mode": mode})
            for prefix in RECORDED_BYTES_PREFIXES.get(name, ()):
                if path.startswith(prefix):
                    url = f"{RAW_BASE}/{ORGANIZATION}/{name}/{commit}/{path}"
                    blobs[url] = _run(repo, "show", f"{commit}:{path}")
        payload[
            f"{API_BASE}/repos/{ORGANIZATION}/{name}/git/trees/{commit}?recursive=1"
        ] = {"tree": entries, "truncated": False}

    return {
        "capture": {
            "schema": "cognovis.provider-capture.v1",
            "provider_identity": f"https://github.com/{ORGANIZATION}",
            "provider_kind": "git-org",
            "captured_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commits": commits,
            "source": (
                "local checkouts at the commits pinned in "
                "cognovis-pi/docs/research/indydevdan-pi-repos.md; tree listings are "
                "git ls-tree output and blob identities are the objects' own Git shas"
            ),
            "note": (
                "tests/test_provider_disler.py::test_capture_matches_live_organization "
                "re-verifies the repository listing and per-repository commits against "
                "the live provider when NETWORK_TESTS=1."
            ),
        },
        "json": payload,
        "bytes": blobs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkouts", required=True)
    parser.add_argument(
        "--output", default=str(Path(__file__).with_name("disler-organization.json"))
    )
    args = parser.parse_args()
    capture = build(Path(args.checkouts).expanduser())
    Path(args.output).write_text(json.dumps(capture, indent=1, sort_keys=True) + "\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
