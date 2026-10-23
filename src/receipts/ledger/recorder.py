"""Typed writes to the ledger: one method per event kind, with derived events.

:class:`Recorder` wraps a :class:`~receipts.ledger.events.LedgerWriter` and builds
every payload exactly as the TypedDicts in :mod:`receipts.ledger.events` define
it, always with ``source``. :meth:`Recorder.record_command` also parses the
command's output and writes any ``test_run``, ``lint_run`` and ``typecheck_run``
events right after the ``command`` event, each pointing back at it through
``command_seq``.

The recorder keeps the ledger's shape honest: ``run_start`` can only be the
first event, nothing can follow ``run_end``, and a ``tool_result`` must answer
a ``tool_call``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, get_args

from receipts.ledger.events import (
    MAX_STREAM_CHARS,
    CommandData,
    DependencyChange,
    DiffData,
    DiffFile,
    EventKind,
    FileWriteData,
    HiddenCheck,
    LedgerWriter,
    RunEndData,
    RunStartData,
    Source,
    ToolCallData,
    ToolResultData,
    cap_stream,
)
from receipts.ledger.parsers.detect import analyze_output
from receipts.ledger.parsers.hidden import hidden_check_data
from receipts.ledger.parsers.results import to_lint_run, to_test_run, to_typecheck_run
from receipts.sandbox.api import CommandOutcome

SOURCES: frozenset[str] = frozenset(get_args(Source))


def sha256_bytes(content: bytes) -> str:
    """Hex SHA-256 of raw file content."""
    return hashlib.sha256(content).hexdigest()


class Recorder:
    """Writes typed, validated events through a :class:`LedgerWriter`.

    Args:
        writer: The ledger to append to (it may already hold events when resuming).
        workspace: Host path of the workspace root. When given, absolute paths
            under it passed to :meth:`record_file_write` are made relative.
    """

    def __init__(self, writer: LedgerWriter, *, workspace: Path | None = None) -> None:
        self._writer = writer
        self._workspace = workspace

    @property
    def writer(self) -> LedgerWriter:
        """The underlying ledger writer."""
        return self._writer

    def _append(self, kind: EventKind, data: Mapping[str, Any]) -> int:
        events = self._writer.events
        if events and events[-1].kind == "run_end":
            raise ValueError("the ledger already has run_end; nothing may follow it")
        source = data.get("source")
        if source not in SOURCES:
            raise ValueError(f"source must be one of {sorted(SOURCES)}, not {source!r}")
        return self._writer.append(kind, data).seq

    def _require_kind(self, seq: int, kind: str, what: str) -> None:
        events = self._writer.events
        if not 0 <= seq < len(events) or events[seq].kind != kind:
            raise ValueError(f"{what} {seq} is not a {kind} event in this ledger")

    def record_run_start(
        self,
        *,
        run_id: str,
        task_id: str,
        agent: str,
        model: str,
        config_id: str,
        workspace: str,
        base_commit: str,
        conditions: Mapping[str, str] | None = None,
        source: Source = "harness",
    ) -> int:
        """Write ``run_start``; it must be the ledger's first event. Returns its seq."""
        if self._writer.events:
            raise ValueError("run_start must be the first event in the ledger")
        data = RunStartData(
            run_id=run_id,
            task_id=task_id,
            agent=agent,
            model=model,
            config_id=config_id,
            workspace=workspace,
            base_commit=base_commit,
            source=source,
        )
        if conditions is not None:
            data["conditions"] = dict(conditions)
        return self._append("run_start", data)

    def record_tool_call(
        self, tool: str, tool_input: Mapping[str, Any], *, source: Source = "agent"
    ) -> int:
        """Write ``tool_call`` for a tool the agent asked for. Returns its seq."""
        return self._append(
            "tool_call", ToolCallData(tool=tool, input=dict(tool_input), source=source)
        )

    def record_tool_result(
        self,
        call_seq: int,
        shown: str,
        *,
        full_chars: int | None = None,
        truncated: bool | None = None,
        is_error: bool = False,
        tool: str | None = None,
        source: Source = "agent",
    ) -> int:
        """Write ``tool_result``: the exact text the agent received for call ``call_seq``.

        Args:
            call_seq: Seq of the matching ``tool_call`` event.
            shown: The text returned to the agent, after any truncation.
            full_chars: Length of the full output before truncation at the tool
                boundary; defaults to ``len(shown)``.
            truncated: Whether the agent saw less than the full output; defaults
                to ``full_chars > len(shown)``. Pass it explicitly when the shown
                text includes an appended truncation notice.
            is_error: The tool reported an error to the agent.
            tool: Tool name; defaults to the name in the ``tool_call`` event.
            source: Usually ``"agent"``.
        """
        self._require_kind(call_seq, "tool_call", "call_seq")
        full = len(shown) if full_chars is None else full_chars
        data = ToolResultData(
            tool=tool if tool is not None else str(self._writer.events[call_seq].data["tool"]),
            call_seq=call_seq,
            shown=shown,
            shown_chars=len(shown),
            full_chars=full,
            truncated=full > len(shown) if truncated is None else truncated,
            is_error=is_error,
            source=source,
        )
        return self._append("tool_result", data)

    def record_command(
        self,
        outcome: CommandOutcome,
        call_seq: int | None,
        source: Source,
        *,
        derive: bool = True,
    ) -> int:
        """Write ``command`` for one process the sandbox ran, then its derived runs.

        Streams longer than :data:`~receipts.ledger.events.MAX_STREAM_CHARS` are
        capped (head and tail kept); the recorded hashes are the sandbox's hashes
        of the full streams. With ``derive``, the output is parsed and one
        ``test_run``, ``lint_run`` or ``typecheck_run`` event is written per run
        recognized, each with ``command_seq`` set to the command's seq and the
        same ``source``. Pass ``derive=False`` for output that is not the agent's
        or the task's test suite (hidden checks).

        Returns:
            The seq of the ``command`` event.
        """
        if call_seq is not None:
            self._require_kind(call_seq, "tool_call", "call_seq")
        stdout, stdout_cut, _ = cap_stream(outcome.stdout, MAX_STREAM_CHARS)
        stderr, stderr_cut, _ = cap_stream(outcome.stderr, MAX_STREAM_CHARS)
        data = CommandData(
            cmd=outcome.cmd,
            cwd=outcome.cwd,
            exit_code=outcome.exit_code,
            duration_s=outcome.duration_s,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=outcome.stdout_truncated or stdout_cut,
            stderr_truncated=outcome.stderr_truncated or stderr_cut,
            stdout_sha256=outcome.stdout_sha256,
            stderr_sha256=outcome.stderr_sha256,
            timed_out=outcome.timed_out,
            call_seq=call_seq,
            source=source,
        )
        seq = self._append("command", data)
        if derive:
            runs = analyze_output(outcome.cmd, outcome.stdout, outcome.stderr, outcome.exit_code)
            for test in runs.tests:
                self._append("test_run", to_test_run(test, seq, source))
            for lint in runs.lints:
                self._append("lint_run", to_lint_run(lint, seq, source))
            for typecheck in runs.typechecks:
                self._append("typecheck_run", to_typecheck_run(typecheck, seq, source))
        return seq

    def _relative(self, path: str | PurePath) -> str:
        pure = PurePosixPath(path.as_posix() if isinstance(path, PurePath) else path)
        if pure.is_absolute():
            if self._workspace is None:
                raise ValueError(f"absolute path {str(pure)!r} needs a workspace to be relative to")
            try:
                pure = PurePosixPath(pure.relative_to(self._workspace.as_posix()))
            except ValueError as exc:
                raise ValueError(f"{str(pure)!r} is outside the workspace") from exc
        text = str(pure)
        if text in ("", ".") or ".." in pure.parts:
            raise ValueError(f"{text!r} is not a file path inside the workspace")
        return text

    def record_file_write(
        self,
        path: str | PurePath,
        before: bytes | None,
        after: bytes | None,
        *,
        call_seq: int | None = None,
        source: Source = "agent",
    ) -> int:
        """Write ``file_write`` from a file's content before and after a change.

        ``op`` follows from presence: no ``before`` is a create, no ``after`` a
        delete, both a modify (also when the bytes are unchanged; equal hashes
        then show the write changed nothing). ``path`` is stored relative to the
        workspace with POSIX separators.
        """
        if before is None and after is None:
            raise ValueError("a file write needs content before, after, or both")
        if call_seq is not None:
            self._require_kind(call_seq, "tool_call", "call_seq")
        data = FileWriteData(
            path=self._relative(path),
            op="create" if before is None else "delete" if after is None else "modify",
            sha256_before=None if before is None else sha256_bytes(before),
            sha256_after=None if after is None else sha256_bytes(after),
            call_seq=call_seq,
            source=source,
        )
        return self._append("file_write", data)

    def record_diff(
        self,
        base: str,
        files: Sequence[DiffFile],
        dependency_changes: Sequence[DependencyChange] = (),
        *,
        source: Source = "snapshot",
    ) -> int:
        """Write ``diff``: the workspace diff against ``base``. Returns its seq."""
        data = DiffData(
            base=base,
            files=list(files),
            dependency_changes=list(dependency_changes),
            source=source,
        )
        return self._append("diff", data)

    def record_hidden_checks(
        self, checks: Sequence[HiddenCheck], *, source: Source = "snapshot"
    ) -> int:
        """Write ``hidden_check`` with pass, fail and total counts. Returns its seq."""
        return self._append("hidden_check", hidden_check_data(list(checks), source))

    def record_run_end(
        self, final_report: str, turns: int, stop_reason: str, *, source: Source = "harness"
    ) -> int:
        """Write ``run_end`` with the agent's final report verbatim; nothing may follow it."""
        data = RunEndData(
            final_report=final_report, turns=turns, stop_reason=stop_reason, source=source
        )
        return self._append("run_end", data)
