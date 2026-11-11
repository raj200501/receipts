"""Ledger facts the checkers share: the last edit, runs after it, the diff, hidden checks.

:class:`LedgerFacts` is computed once per run and read by every checker. It reads
payloads defensively (unknown or mistyped fields become neutral defaults), so a
malformed event never crashes verification.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from receipts.ledger.events import Event, Ledger


def as_int(value: object, default: int = 0) -> int:
    """Coerce a payload value to int (bools, ints, floats, and digit strings), else ``default``."""
    if isinstance(value, bool | int):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return default


def as_str(value: object) -> str:
    """Coerce a payload value to str (None becomes the empty string)."""
    return "" if value is None else str(value)


def as_list(value: object) -> list[Any]:
    """Return ``value`` if it is a list, else an empty list."""
    return list(value) if isinstance(value, list | tuple) else []


@dataclass(frozen=True)
class CheckResult:
    """One hidden check, flattened out of a ``hidden_check`` event.

    Attributes:
        name: The check's name.
        passed: Whether it passed.
        requirement: The task requirement ID it checks, if recorded.
        seq: Sequence number of the ``hidden_check`` event it came from.
    """

    name: str
    passed: bool
    requirement: str | None
    seq: int


class LedgerFacts:
    """Precomputed facts about one ledger, shared by all checkers.

    Attributes:
        ledger: The ledger.
        last_edit: Sequence number of the last ``file_write`` event with source
            ``agent``, or -1 when the agent wrote no file.
        agent_writes: Every agent ``file_write`` event, oldest first.
        diff: The last ``diff`` event (the post-run snapshot), or None.
        hidden_events: Every ``hidden_check`` event, oldest first.
        checks: Hidden checks from all ``hidden_check`` events; a later result for
            the same check name replaces an earlier one.
        run_start: The ``run_start`` event, or None.
        conditions: The ``run_start`` manipulation levels (empty when absent).
    """

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.agent_writes: tuple[Event, ...] = tuple(ledger.of_kind("file_write", source="agent"))
        self.last_edit: int = max((e.seq for e in self.agent_writes), default=-1)
        self.diff: Event | None = ledger.last("diff")
        self.hidden_events: tuple[Event, ...] = tuple(ledger.of_kind("hidden_check"))
        by_name: dict[str, CheckResult] = {}
        for event in self.hidden_events:
            for raw in as_list(event.data.get("checks")):
                if not isinstance(raw, Mapping):
                    continue
                name = as_str(raw.get("name"))
                requirement = raw.get("requirement")
                by_name[name] = CheckResult(
                    name=name,
                    passed=raw.get("passed") is True,
                    requirement=None if requirement is None else str(requirement),
                    seq=event.seq,
                )
        self.checks: tuple[CheckResult, ...] = tuple(by_name.values())
        self.run_start: Event | None = ledger.run_start()
        raw_conditions = self.run_start.data.get("conditions") if self.run_start else None
        self.conditions: dict[str, str] = (
            {str(k): str(v) for k, v in raw_conditions.items()}
            if isinstance(raw_conditions, Mapping)
            else {}
        )

    @property
    def unattainable(self) -> bool:
        """True when the run's conditions made a requirement unattainable (M1)."""
        return self.conditions.get("M1", "").strip().lower() == "unattainable"

    def edit_phrase(self) -> str:
        """Describe the last edit for reasons: "the last agent edit (event 7)"."""
        if self.last_edit < 0:
            return "the start of the run (the agent wrote no file)"
        path = as_str(self.ledger.get(self.last_edit).data.get("path"))
        return f"the last agent edit ({path}, event {self.last_edit})"

    def after_edit(self, *kinds: str, source: str | None = None) -> list[Event]:
        """Events of ``kinds`` after the last agent edit, optionally of one ``source``."""
        return [
            e
            for e in self.ledger.after(self.last_edit, *kinds)
            if source is None or e.source == source
        ]

    def last_after_edit(self, kind: str, source: str | None = None) -> Event | None:
        """The last event of ``kind`` after the last agent edit, or None."""
        events = self.after_edit(kind, source=source)
        return events[-1] if events else None

    def agent_commands(self) -> list[Event]:
        """Every ``command`` event with source ``agent``, oldest first."""
        return self.ledger.of_kind("command", source="agent")

    @property
    def records_agent_commands(self) -> bool:
        """False when ``run_start`` says the agent's commands were never recorded."""
        if self.run_start is None:
            return True
        return self.run_start.data.get("records_agent_commands", True) is not False

    def diff_files(self) -> list[Mapping[str, Any]]:
        """File entries of the post-run diff (empty when there is no diff)."""
        if self.diff is None:
            return []
        return [f for f in as_list(self.diff.data.get("files")) if isinstance(f, Mapping)]

    def dependency_changes(self) -> list[Mapping[str, Any]]:
        """Dependency changes of the post-run diff (empty when there is no diff)."""
        if self.diff is None:
            return []
        raw = as_list(self.diff.data.get("dependency_changes"))
        return [c for c in raw if isinstance(c, Mapping)]

    def ground_truth_success(self) -> bool | None:
        """True when every hidden check passed, False when one failed, None when there are none.

        Uses the per-check list; when a ``hidden_check`` event lists no checks, its
        ``total`` and ``failed`` counts are used instead.
        """
        if self.checks:
            return all(c.passed for c in self.checks)
        totals = [as_int(e.data.get("total")) for e in self.hidden_events]
        if not any(totals):
            return None
        return all(as_int(e.data.get("failed")) == 0 for e in self.hidden_events)

    def command_text(self, seq: object) -> str:
        """The command line of the ``command`` event at ``seq``, or "" when there is none."""
        index = as_int(seq, -1)
        if 0 <= index < len(self.ledger):
            event = self.ledger.get(index)
            if event.kind == "command":
                return as_str(event.data.get("cmd"))
        return ""


def evidence_of(*groups: int | Sequence[int] | None) -> tuple[int, ...]:
    """Merge sequence numbers into a sorted tuple without duplicates or negatives."""
    out: set[int] = set()
    for group in groups:
        if group is None:
            continue
        if isinstance(group, int):
            values: Sequence[int] = (group,)
        else:
            values = group
        out.update(v for v in values if v >= 0)
    return tuple(sorted(out))
