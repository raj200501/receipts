"""Render a ledger as a plain-text fact sheet.

Seeded-report writers and gold-label adjudicators (E0a) work from this sheet, so
they see what happened in a run without seeing receipts' extraction or
verification code. It lists, in order, every agent command with its exit code,
every parsed test, lint, or type-check run, every file write, the final diff and
dependency changes, the hidden-check results, and the run's conditions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from receipts.ledger.events import Event, Ledger


def _first_line(text: str, limit: int = 160) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[: limit - 3] + "..."


def _describe(event: Event, by_seq: Mapping[int, Event]) -> str | None:
    d: Mapping[str, Any] = event.data
    src = event.source
    if event.kind == "command":
        tail = _first_line(str(d.get("stderr", "")) or str(d.get("stdout", "")))
        note = " (timed out)" if d.get("timed_out") else ""
        return (
            f"[{event.seq}] {src} command `{d.get('cmd')}` exit {d.get('exit_code')}{note}: {tail}"
        )
    if event.kind == "test_run":
        failing = ", ".join(map(str, d.get("failing", []))) or "none"
        extra = " collection error;" if d.get("collection_error") else ""
        return (
            f"[{event.seq}] {src} test run ({d.get('framework')}): {d.get('passed')} passed, "
            f"{d.get('failed')} failed, {d.get('errors')} errors, {d.get('skipped')} skipped, "
            f"{d.get('total')} total;{extra} failing: {failing}"
        )
    if event.kind in ("lint_run", "typecheck_run"):
        label = "lint" if event.kind == "lint_run" else "type check"
        return f"[{event.seq}] {src} {label} ({d.get('tool')}): {d.get('errors')} errors"
    if event.kind == "file_write":
        return f"[{event.seq}] {src} file {d.get('op')}: {d.get('path')}"
    if event.kind == "diff":
        files = ", ".join(f"{f.get('status')} {f.get('path')}" for f in d.get("files", []))
        deps = "; ".join(
            f"{c.get('change')} {c.get('name')} {c.get('old') or ''}->{c.get('new') or ''}"
            f" in {c.get('manifest')}"
            for c in d.get("dependency_changes", [])
        )
        return (
            f"[{event.seq}] final diff vs {str(d.get('base', ''))[:12]}: {files or 'no changes'}"
            + (f"; dependency changes: {deps}" if deps else "")
        )
    if event.kind == "hidden_check":
        parts = []
        for check in d.get("checks", []):
            req = check.get("requirement")
            label = f"{check.get('name')}" + (f" ({req})" if req else "")
            parts.append(f"{label}={'pass' if check.get('passed') else 'FAIL'}")
        checks = ", ".join(parts)
        return f"[{event.seq}] hidden checks: {d.get('passed')}/{d.get('total')} passed: {checks}"
    if event.kind == "tool_result" and d.get("truncated"):
        call = by_seq.get(int(d.get("call_seq", -1)))
        tool = call.data.get("tool") if call is not None else d.get("tool")
        return (
            f"[{event.seq}] note: the agent saw only {d.get('shown_chars')} of "
            f"{d.get('full_chars')} characters of the {tool} output"
        )
    return None


def fact_sheet(ledger: Ledger | Iterable[Event], *, include_report: bool = False) -> str:
    """Return the fact sheet for a ledger.

    Args:
        ledger: The run's ledger.
        include_report: Append the agent's own final report (off for writers of
            seeded reports, who must not copy it).
    """
    view = ledger if isinstance(ledger, Ledger) else Ledger(ledger)
    by_seq = {e.seq: e for e in view}
    lines: list[str] = []
    start = view.run_start()
    if start is not None:
        d = start.data
        conditions = d.get("conditions") or {}
        cond = ", ".join(f"{k}={v}" for k, v in sorted(dict(conditions).items())) or "none"
        lines.append(
            f"Run {d.get('run_id')} on task {d.get('task_id')} by {d.get('agent')} "
            f"({d.get('model')}); conditions: {cond}"
        )
    for event in view:
        text = _describe(event, by_seq)
        if text is not None:
            lines.append(text)
    end = view.last("run_end")
    if end is not None:
        lines.append(
            f"Run ended: {end.data.get('stop_reason')} after {end.data.get('turns')} turns"
        )
        if include_report:
            lines.append("Final report:\n" + str(end.data.get("final_report", "")))
    return "\n".join(lines) + "\n"
