"""The ground-truth event ledger: schema, hash chain, writer, reader, and queries.

A ledger is an append-only JSONL file. Each line is one :class:`Event`::

    {"seq": 3, "ts": 1761184800.25, "kind": "command", "data": {...},
     "prev": "<hash of event 2>", "hash": "<sha256 of this event>"}

``hash`` is the SHA-256 of the canonical JSON of ``{seq, ts, kind, data, prev}``
(sorted keys, no whitespace, UTF-8). The first event's ``prev`` is 64 zeros.
Editing, dropping, or reordering any event breaks the chain, which
:func:`verify_chain` detects.

Events never come from the agent's own transcript. They come from the executor
(minimal-agent), from PreToolUse and PostToolUse hooks (Claude Code), and from
the post-run snapshot (git diff, a rerun of the tests, hidden checks). ``source``
in each payload says which: ``"agent"`` for actions the agent took, ``"snapshot"``
for post-run ground truth, ``"harness"`` for run bookkeeping.

Payload schemas per kind are the TypedDicts below. They are the contract between
the recorder (which writes events), the verifier (which reads them), and the
analysis code. Unknown extra keys are allowed and ignored by readers.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, get_args

GENESIS = "0" * 64

EventKind = Literal[
    "run_start",
    "tool_call",
    "tool_result",
    "command",
    "file_write",
    "test_run",
    "lint_run",
    "typecheck_run",
    "diff",
    "hidden_check",
    "run_end",
]
EVENT_KINDS: frozenset[str] = frozenset(get_args(EventKind))

Source = Literal["agent", "snapshot", "harness"]


class RunStartData(TypedDict):
    """``run_start``: written once, first."""

    run_id: str
    task_id: str
    agent: str  # driver name, e.g. "claude-code" or "minimal-agent"
    model: str  # model ID with revision or file hash
    config_id: str
    workspace: str
    base_commit: str  # git commit of the task repository before the run
    source: Source
    conditions: NotRequired[dict[str, str]]  # manipulation levels, e.g. {"M2": "truncated"}


class ToolCallData(TypedDict):
    """``tool_call``: the agent asked for a tool (PreToolUse, or minimal-agent dispatch)."""

    tool: str  # e.g. "Bash", "Edit", "bash", "run_tests"
    input: dict[str, Any]  # tool input as the agent sent it
    source: Source


class ToolResultData(TypedDict):
    """``tool_result``: what the agent actually received back (PostToolUse)."""

    tool: str
    call_seq: int  # seq of the matching tool_call
    shown: str  # the exact text returned to the agent (after any truncation)
    shown_chars: int
    full_chars: int  # length before truncation at the tool boundary
    truncated: bool
    is_error: bool
    source: Source


class CommandData(TypedDict):
    """``command``: one process the sandbox ran, with its true, untruncated outcome."""

    cmd: str  # the command line as a string (shell form)
    cwd: str  # relative to the workspace root
    exit_code: int
    duration_s: float
    stdout: str  # capped at MAX_STREAM_CHARS; see *_truncated
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_sha256: str  # hash of the full stream before capping
    stderr_sha256: str
    timed_out: bool
    call_seq: int | None  # tool_call that caused it; None for snapshot or harness commands
    source: Source


class FileWriteData(TypedDict):
    """``file_write``: a file was created, modified, or deleted."""

    path: str  # relative to the workspace root, POSIX separators
    op: Literal["create", "modify", "delete"]
    sha256_before: str | None
    sha256_after: str | None
    call_seq: int | None
    source: Source


class TestCase(TypedDict):
    """One test outcome inside a ``test_run``."""

    name: str  # e.g. "tests/test_parse.py::test_empty"
    outcome: Literal["passed", "failed", "error", "skipped"]


class TestRunData(TypedDict):
    """``test_run``: a parsed test-suite run (derived from a ``command``)."""

    framework: str  # "pytest", "junit", "node-test", "jest", "vitest", "mocha"
    command_seq: int  # the command event it was parsed from
    passed: int
    failed: int
    errors: int
    skipped: int
    total: int
    failing: list[str]  # names of failed or errored tests
    cases: NotRequired[list[TestCase]]
    collection_error: NotRequired[bool]  # the run aborted before tests ran
    source: Source


class LintRunData(TypedDict):
    """``lint_run``: a parsed linter run (ruff, flake8, eslint)."""

    tool: str
    command_seq: int
    errors: int
    warnings: int
    source: Source


class TypecheckRunData(TypedDict):
    """``typecheck_run``: a parsed type-checker run (mypy, pyright, tsc)."""

    tool: str
    command_seq: int
    errors: int
    source: Source


class DiffFile(TypedDict):
    """One file in a ``diff``."""

    path: str
    status: Literal["A", "M", "D", "R"]
    added: int
    removed: int
    old_path: NotRequired[str]  # for renames


class DependencyChange(TypedDict):
    """One dependency change found in a manifest diff."""

    manifest: str  # e.g. "pyproject.toml", "requirements.txt", "package.json"
    name: str
    change: Literal["added", "removed", "changed"]
    old: str | None  # version spec before
    new: str | None  # version spec after


class DiffData(TypedDict):
    """``diff``: the workspace diff against ``base_commit`` (post-run snapshot)."""

    base: str
    files: list[DiffFile]
    dependency_changes: list[DependencyChange]
    source: Source


class HiddenCheck(TypedDict):
    """One hidden ground-truth check."""

    name: str
    passed: bool
    requirement: NotRequired[str]  # task requirement ID it checks, e.g. "R2"


class HiddenCheckData(TypedDict):
    """``hidden_check``: task ground truth the agent never sees (post-run snapshot)."""

    passed: int
    failed: int
    total: int
    checks: list[HiddenCheck]
    source: Source


class RunEndData(TypedDict):
    """``run_end``: written once, last."""

    final_report: str  # the agent's final report text, verbatim
    turns: int
    stop_reason: str  # "finished", "max_turns", "timeout", "error", "usage_limit"
    source: Source


MAX_STREAM_CHARS = 262_144


def canonical_json(obj: Any) -> str:
    """Serialize ``obj`` deterministically: sorted keys, compact separators, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cap_stream(text: str, limit: int = MAX_STREAM_CHARS) -> tuple[str, bool, str]:
    """Return ``(capped_text, truncated, sha256_of_full_text)`` for a command stream.

    When truncated, the head and tail are kept so that both the first error and
    the final summary line survive.
    """
    digest = sha256_text(text)
    if len(text) <= limit:
        return text, False, digest
    half = limit // 2
    marker = f"\n[... {len(text) - 2 * half} chars elided by receipts ...]\n"
    return text[:half] + marker + text[-half:], True, digest


@dataclass(frozen=True)
class Event:
    """One ledger event. Construct through :class:`LedgerWriter` or :func:`read_ledger`."""

    seq: int
    ts: float
    kind: str
    data: Mapping[str, Any]
    prev: str
    hash: str

    @staticmethod
    def compute_hash(seq: int, ts: float, kind: str, data: Mapping[str, Any], prev: str) -> str:
        """Return the chain hash for an event's content."""
        body = {"seq": seq, "ts": ts, "kind": kind, "data": dict(data), "prev": prev}
        return sha256_text(canonical_json(body))

    def to_json(self) -> str:
        """Return the event as one canonical JSON line (without the newline)."""
        return canonical_json(
            {
                "seq": self.seq,
                "ts": self.ts,
                "kind": self.kind,
                "data": dict(self.data),
                "prev": self.prev,
                "hash": self.hash,
            }
        )

    @classmethod
    def from_json(cls, line: str) -> Event:
        """Parse one JSONL line; raises ValueError on malformed input."""
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("ledger line is not an object")
        try:
            return cls(
                seq=int(raw["seq"]),
                ts=float(raw["ts"]),
                kind=str(raw["kind"]),
                data=dict(raw["data"]),
                prev=str(raw["prev"]),
                hash=str(raw["hash"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"ledger line missing or mistyped field: {exc}") from exc

    @property
    def source(self) -> str:
        """The payload's ``source`` (``agent``, ``snapshot``, or ``harness``)."""
        return str(self.data.get("source", ""))


class LedgerWriter:
    """Append-only writer for a hash-chained JSONL ledger.

    Opening an existing ledger resumes its chain after verifying it. Each append is
    flushed and fsynced so a crash loses at most the event being written.
    """

    def __init__(self, path: Path, clock: Any = time.time) -> None:
        self.path = path
        self._clock = clock
        self._events: list[Event] = read_ledger(path) if path.is_file() else []
        problems = verify_chain(self._events)
        if problems:
            raise ValueError(f"refusing to extend a broken ledger: {problems[0]}")

    @property
    def events(self) -> Sequence[Event]:
        """Events written so far, oldest first."""
        return tuple(self._events)

    def append(self, kind: str, data: Mapping[str, Any], ts: float | None = None) -> Event:
        """Append one event of ``kind`` with payload ``data`` and return it."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        seq = len(self._events)
        prev = self._events[-1].hash if self._events else GENESIS
        stamp = float(self._clock() if ts is None else ts)
        payload = json.loads(canonical_json(dict(data)))  # normalize to plain JSON types
        event = Event(
            seq, stamp, kind, payload, prev, Event.compute_hash(seq, stamp, kind, payload, prev)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._events.append(event)
        return event


def read_ledger(path: Path) -> list[Event]:
    """Read every event from a ledger file (blank lines are ignored)."""
    events: list[Event] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                events.append(Event.from_json(line))
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
    return events


def verify_chain(events: Sequence[Event]) -> list[str]:
    """Return every hash-chain problem in ``events`` (empty means intact)."""
    problems: list[str] = []
    prev = GENESIS
    for index, event in enumerate(events):
        if event.seq != index:
            problems.append(f"event {index} has seq {event.seq}")
        if event.prev != prev:
            problems.append(f"event {index} does not chain to its predecessor")
        expected = Event.compute_hash(event.seq, event.ts, event.kind, event.data, event.prev)
        if event.hash != expected:
            problems.append(f"event {index} hash does not match its content")
        if event.kind not in EVENT_KINDS:
            problems.append(f"event {index} has unknown kind {event.kind!r}")
        prev = event.hash
    return problems


class Ledger:
    """Read-only view over a verified sequence of events, with common queries."""

    def __init__(self, events: Iterable[Event]) -> None:
        self.events: tuple[Event, ...] = tuple(events)

    @classmethod
    def load(cls, path: Path, *, verify: bool = True) -> Ledger:
        """Load a ledger file, raising ValueError if ``verify`` and the chain is broken."""
        events = read_ledger(path)
        if verify:
            problems = verify_chain(events)
            if problems:
                raise ValueError(f"{path}: {problems[0]}")
        return cls(events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def get(self, seq: int) -> Event:
        """Return the event with sequence number ``seq``."""
        return self.events[seq]

    def of_kind(self, *kinds: str, source: str | None = None) -> list[Event]:
        """Events of any of ``kinds``, optionally restricted to one ``source``, oldest first."""
        return [
            e for e in self.events if e.kind in kinds and (source is None or e.source == source)
        ]

    def last(self, kind: str, source: str | None = None) -> Event | None:
        """The most recent event of ``kind`` (and ``source``), or None."""
        matches = self.of_kind(kind, source=source)
        return matches[-1] if matches else None

    def after(self, seq: int, *kinds: str) -> list[Event]:
        """Events with sequence number greater than ``seq``, optionally of ``kinds``."""
        return [e for e in self.events if e.seq > seq and (not kinds or e.kind in kinds)]

    def run_start(self) -> Event | None:
        """The ``run_start`` event, if present."""
        return self.last("run_start")

    def final_report(self) -> str | None:
        """The agent's final report text from ``run_end``, if present."""
        end = self.last("run_end")
        return None if end is None else str(end.data.get("final_report", ""))
