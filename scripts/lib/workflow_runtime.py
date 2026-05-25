"""
workflow_runtime.py — Spike runtime for Anthropic Workflow JS specs.

This is a constrained proof-of-concept:
- it reads a workflow spec as source text
- enforces inert-spine bans
- extracts a small JSON-compatible meta block
- dispatches `agent()` leaves through pluggable executors
- journals leaf results by hash(prompt + opts)
"""

from __future__ import annotations

import abc
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


class SpineConstraintError(ValueError):
    """Raised when the workflow spine uses a banned operation."""


class SpineConstraintChecker:
    """Heuristic static analysis for inert-spine rules."""

    _BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("filesystem require()", re.compile(r"\brequire\s*\(")),
        ("filesystem import fs", re.compile(r"\bimport\b[^;]*['\"]fs(?:/[^'\"]+)?['\"]")),
        (
            "filesystem import child_process",
            re.compile(r"\bimport\b[^;]*['\"]child_process(?:/[^'\"]+)?['\"]"),
        ),
        ("filesystem import net", re.compile(r"\bimport\b[^;]*['\"]net(?:/[^'\"]+)?['\"]")),
        ("shell exec", re.compile(r"\b(?:exec|spawn|system|popen)\s*\(")),
        ("network fetch", re.compile(r"\bfetch\s*\(")),
        ("network net module", re.compile(r"\bnet\.")),
        ("filesystem api", re.compile(r"\bfs\.")),
        ("Date.now", re.compile(r"\bDate\.now\s*\(")),
        ("Math.random", re.compile(r"\bMath\.random\s*\(")),
        ("new Date()", re.compile(r"\bnew\s+Date\s*\(\s*\)")),
    )

    def find_violations(self, source: str) -> list[str]:
        """Return a list of banned constructs detected in source."""
        violations: list[str] = []
        stripped = self._strip_comments(source)

        for label, pattern in self._BANNED_PATTERNS:
            if pattern.search(stripped):
                violations.append(label)

        return violations

    def validate(self, source: str) -> None:
        """Raise when the workflow spine is not inert."""
        violations = self.find_violations(source)
        if violations:
            raise SpineConstraintError(
                "Workflow spine is not inert: " + ", ".join(violations)
            )

    @staticmethod
    def _strip_comments(source: str) -> str:
        """Remove line and block comments while leaving strings untouched."""
        without_block_comments = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
        return re.sub(r"//.*?$", " ", without_block_comments, flags=re.M)


class AgentExecutor(abc.ABC):
    """Interface for workflow leaf executors."""

    adapter_name: str

    @abc.abstractmethod
    def run(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        """Execute a single agent leaf."""


class ClaudeAgentExecutor(AgentExecutor):
    """Spike executor for the `claude-agent` adapter."""

    adapter_name = "claude-agent"

    def __init__(self, command_runner: Optional[Callable[[list[str]], Any]] = None) -> None:
        self._command_runner = command_runner

    def build_command(self, prompt: str, opts: dict[str, Any]) -> list[str]:
        """Build the claude leaf command for the requested prompt."""
        command = ["claude", "-p", "--output-format", "json"]
        model = opts.get("model")
        if isinstance(model, str) and model:
            command.extend(["--model", model])
        command.append(prompt)
        return command

    def run(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        """Return a leaf execution record or invoke the injected runner."""
        command = self.build_command(prompt, opts)
        if self._command_runner is None:
            return {
                "adapter": self.adapter_name,
                "command": command,
                "prompt": prompt,
                "opts": dict(opts),
                "status": "prepared",
            }

        result = self._command_runner(command)
        return {
            "adapter": self.adapter_name,
            "command": command,
            "prompt": prompt,
            "opts": dict(opts),
            "status": "executed",
            "result": result,
        }


def _canonical_payload(prompt: str, opts: dict[str, Any]) -> str:
    return json.dumps({"prompt": prompt, "opts": opts}, sort_keys=True, separators=(",", ":"))


def _hash_prompt_opts(prompt: str, opts: dict[str, Any]) -> str:
    payload = _canonical_payload(prompt, opts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class JournalStore:
    """Dict-backed journal with optional JSON persistence."""

    entries: dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    def key_for(self, prompt: str, opts: dict[str, Any]) -> str:
        return _hash_prompt_opts(prompt, opts)

    def get(self, prompt: str, opts: dict[str, Any]) -> Any:
        return self.entries.get(self.key_for(prompt, opts))

    def put(self, prompt: str, opts: dict[str, Any], value: Any) -> str:
        key = self.key_for(prompt, opts)
        self.entries[key] = value
        return key

    def to_dict(self) -> dict[str, Any]:
        return {"entries": dict(self.entries)}

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Optional[Path] = None) -> "JournalStore":
        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}
        return cls(entries=dict(entries), path=path)

    @classmethod
    def from_path(cls, path: Path) -> "JournalStore":
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
        return cls.from_dict(raw, path=path)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


class ResumeContext:
    """Load/save wrapper around the journal store."""

    def __init__(self, path: Optional[Path] = None, journal: Optional[JournalStore] = None) -> None:
        self.path = path
        self.journal = journal or JournalStore(path=path)
        if self.path is not None and self.path.exists():
            self.load()

    def load(self) -> JournalStore:
        if self.path is None:
            return self.journal
        self.journal = JournalStore.from_path(self.path)
        return self.journal

    def save(self) -> None:
        if self.path is not None:
            self.journal.path = self.path
        self.journal.save()


class WorkflowRuntime:
    """Read-only spike runtime for workflow JS specs."""

    def __init__(
        self,
        *,
        journal: Optional[JournalStore] = None,
        resume_context: Optional[ResumeContext] = None,
        executor_registry: Optional[dict[str, AgentExecutor]] = None,
        constraint_checker: Optional[SpineConstraintChecker] = None,
    ) -> None:
        self.constraint_checker = constraint_checker or SpineConstraintChecker()
        self.resume_context = resume_context
        self.journal = journal or (resume_context.journal if resume_context else JournalStore())
        self.executor_registry = executor_registry or {
            "claude-agent": ClaudeAgentExecutor(),
        }

    def run(self, spec_path: str | Path, args: dict[str, Any]) -> dict[str, Any]:
        """Load a workflow spec, validate the spine, and execute its agent leaves."""
        path = Path(spec_path)
        source = path.read_text(encoding="utf-8")
        self.constraint_checker.validate(source)

        meta = self._extract_meta(source)
        agent_calls = self._extract_agent_calls(source)

        leaf_results: list[dict[str, Any]] = []
        for call in agent_calls:
            prompt = call["prompt"]
            opts = dict(call["opts"])
            slot_target = self._resolve_slot_target(args, opts)
            opts.setdefault("slot_target", slot_target)
            leaf_results.append(self._run_leaf(prompt, opts))

        result = {
            "status": "ok",
            "spec": str(path),
            "meta": meta,
            "args": dict(args),
            "leaf_results": leaf_results,
            "journal": dict(self.journal.entries),
        }

        if self.resume_context is not None:
            self.resume_context.save()

        return result

    def _run_leaf(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        cached = self.journal.get(prompt, opts)
        if cached is not None:
            return {
                "cached": True,
                "journal_key": self.journal.key_for(prompt, opts),
                "result": cached,
                "prompt": prompt,
                "opts": dict(opts),
            }

        adapter_name = self._resolve_adapter_name(opts)
        executor = self.executor_registry.get(adapter_name)
        if executor is None:
            raise ValueError(f"No executor registered for adapter {adapter_name!r}")

        result = executor.run(prompt, opts)
        journal_key = self.journal.put(prompt, opts, result)
        return {
            "cached": False,
            "journal_key": journal_key,
            "result": result,
            "prompt": prompt,
            "opts": dict(opts),
        }

    @staticmethod
    def _resolve_adapter_name(opts: dict[str, Any]) -> str:
        slot_target = opts.get("slot_target", {})
        if isinstance(slot_target, dict):
            adapter = slot_target.get("adapter")
            if isinstance(adapter, str) and adapter:
                return adapter
        adapter = opts.get("adapter")
        if isinstance(adapter, str) and adapter:
            return adapter
        return "claude-agent"

    @staticmethod
    def _resolve_slot_target(args: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any] | None:
        route_profiles = args.get("route_profiles")
        route_profile_name = args.get("route_profile")
        workflow = args.get("workflow", "full")
        slot_name = opts.get("slot")

        if not (
            isinstance(route_profiles, dict)
            and isinstance(route_profile_name, str)
            and route_profile_name
            and isinstance(slot_name, str)
            and slot_name
        ):
            return None

        profile = route_profiles.get(route_profile_name, {})
        slots = profile.get("slots", {}) if isinstance(profile, dict) else {}
        workflow_slots = slots.get(workflow, {}) if isinstance(slots, dict) else {}
        slot_target = workflow_slots.get(slot_name, {}) if isinstance(workflow_slots, dict) else {}
        return slot_target if isinstance(slot_target, dict) else None

    @staticmethod
    def _extract_meta(source: str) -> dict[str, Any]:
        marker = "export const meta ="
        start = source.find(marker)
        if start == -1:
            return {}
        brace_start = source.find("{", start)
        if brace_start == -1:
            return {}
        block, _ = WorkflowRuntime._extract_balanced(source, brace_start, "{", "}")
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_agent_calls(source: str) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        cursor = 0
        marker = "await agent("
        while True:
            idx = source.find(marker, cursor)
            if idx == -1:
                break
            paren_start = source.find("(", idx)
            if paren_start == -1:
                break
            call_block, call_end = WorkflowRuntime._extract_balanced(source, paren_start, "(", ")")
            args_text = call_block[1:-1].strip()
            prompt_text, opts_text = WorkflowRuntime._split_agent_args(args_text)
            calls.append(
                {
                    "prompt": json.loads(prompt_text),
                    "opts": json.loads(opts_text),
                }
            )
            cursor = call_end
        return calls

    @staticmethod
    def _split_agent_args(args_text: str) -> tuple[str, str]:
        comma_index = WorkflowRuntime._find_top_level_comma(args_text)
        if comma_index == -1:
            raise ValueError("agent() call must include prompt and opts")
        prompt_text = args_text[:comma_index].strip()
        opts_text = args_text[comma_index + 1 :].strip()
        return prompt_text, opts_text

    @staticmethod
    def _find_top_level_comma(source: str) -> int:
        depth = 0
        in_string = False
        string_delim = ""
        escape = False
        for index, char in enumerate(source):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == string_delim:
                    in_string = False
                continue

            if char in ('"', "'"):
                in_string = True
                string_delim = char
                continue
            if char in "{[(":
                depth += 1
                continue
            if char in "}])":
                depth -= 1
                continue
            if char == "," and depth == 0:
                return index
        return -1

    @staticmethod
    def _extract_balanced(source: str, start_index: int, open_char: str, close_char: str) -> tuple[str, int]:
        depth = 0
        in_string = False
        string_delim = ""
        escape = False
        for index in range(start_index, len(source)):
            char = source[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == string_delim:
                    in_string = False
                continue
            if char in ('"', "'"):
                in_string = True
                string_delim = char
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return source[start_index : index + 1], index + 1
        raise ValueError(f"Unbalanced {open_char}{close_char} block in workflow source")
