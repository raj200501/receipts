"""Builders for SYNTHETIC ledgers and claims used by the verifier tests.

Every ledger built here is hand-made test data written through LedgerWriter with
a fake clock. None of it comes from a real agent run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from receipts.claims.types import Claim, ClaimType, ParamValue
from receipts.ledger.events import Ledger, LedgerWriter

SYNTHETIC_NOTE = "synthetic ledger hand-built for receipts.verify tests"


class SyntheticLedger:
    """Append synthetic events through LedgerWriter; every method returns the new seq."""

    def __init__(self, path: Path) -> None:
        self._clock = 1_761_184_800.0
        self.writer = LedgerWriter(path, clock=self._tick)

    def _tick(self) -> float:
        self._clock += 1.0
        return self._clock

    def _add(self, kind: str, data: Mapping[str, Any]) -> int:
        return self.writer.append(kind, data).seq

    def start(
        self,
        conditions: Mapping[str, str] | None = None,
        *,
        records_agent_commands: bool = True,
    ) -> int:
        """Append run_start (labeled synthetic)."""
        data: dict[str, Any] = {
            "run_id": "synthetic-run",
            "task_id": "synthetic-task",
            "agent": "synthetic",
            "model": "synthetic",
            "config_id": "synthetic",
            "workspace": "/synthetic/ws",
            "base_commit": "0" * 40,
            "source": "harness",
            "note": SYNTHETIC_NOTE,
        }
        if conditions is not None:
            data["conditions"] = dict(conditions)
        if not records_agent_commands:
            data["records_agent_commands"] = False
        return self._add("run_start", data)

    def command(
        self,
        cmd: str,
        exit_code: int = 0,
        *,
        source: str = "agent",
        timed_out: bool = False,
    ) -> int:
        """Append a command event."""
        return self._add(
            "command",
            {
                "cmd": cmd,
                "cwd": ".",
                "exit_code": exit_code,
                "duration_s": 0.5,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "stdout_sha256": "0" * 64,
                "stderr_sha256": "0" * 64,
                "timed_out": timed_out,
                "call_seq": None,
                "source": source,
            },
        )

    def write(self, path: str, op: str = "modify", *, source: str = "agent") -> int:
        """Append a file_write event."""
        return self._add(
            "file_write",
            {
                "path": path,
                "op": op,
                "sha256_before": None if op == "create" else "a" * 64,
                "sha256_after": None if op == "delete" else "b" * 64,
                "call_seq": None,
                "source": source,
            },
        )

    def tests(
        self,
        passed: int = 0,
        failed: int = 0,
        errors: int = 0,
        skipped: int = 0,
        *,
        failing: Sequence[str] = (),
        source: str = "agent",
        collection_error: bool | None = None,
        cmd: str = "pytest -q",
        framework: str = "pytest",
        total: int | None = None,
    ) -> int:
        """Append a command and the test_run parsed from it; returns the test_run seq."""
        code = 0 if not (failed or errors or collection_error) else 1
        command_seq = self.command(cmd, code, source=source)
        data: dict[str, Any] = {
            "framework": framework,
            "command_seq": command_seq,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "total": passed + failed + errors + skipped if total is None else total,
            "failing": list(failing),
            "source": source,
        }
        if collection_error is not None:
            data["collection_error"] = collection_error
        return self._add("test_run", data)

    def lint(self, errors: int, *, tool: str = "ruff", source: str = "agent") -> int:
        """Append a command and the lint_run parsed from it; returns the lint_run seq."""
        command_seq = self.command(f"{tool} check .", 1 if errors else 0, source=source)
        return self._add(
            "lint_run",
            {
                "tool": tool,
                "command_seq": command_seq,
                "errors": errors,
                "warnings": 0,
                "source": source,
            },
        )

    def typecheck(self, errors: int, *, tool: str = "mypy", source: str = "agent") -> int:
        """Append a command and the typecheck_run parsed from it; returns its seq."""
        command_seq = self.command(f"{tool} src", 1 if errors else 0, source=source)
        return self._add(
            "typecheck_run",
            {"tool": tool, "command_seq": command_seq, "errors": errors, "source": source},
        )

    def diff(
        self,
        files: Sequence[Mapping[str, Any]] = (),
        deps: Sequence[Mapping[str, Any]] = (),
    ) -> int:
        """Append a snapshot diff event."""
        full = [{"added": 1, "removed": 0, **f} for f in files]
        return self._add(
            "diff",
            {
                "base": "0" * 40,
                "files": full,
                "dependency_changes": list(deps),
                "source": "snapshot",
            },
        )

    def hidden(self, checks: Sequence[tuple[str, bool, str | None]]) -> int:
        """Append a hidden_check event from (name, passed, requirement) triples."""
        listed: list[dict[str, Any]] = []
        for name, ok, requirement in checks:
            entry: dict[str, Any] = {"name": name, "passed": ok}
            if requirement is not None:
                entry["requirement"] = requirement
            listed.append(entry)
        passed = sum(1 for _, ok, _ in checks if ok)
        return self._add(
            "hidden_check",
            {
                "passed": passed,
                "failed": len(checks) - passed,
                "total": len(checks),
                "checks": listed,
                "source": "snapshot",
            },
        )

    def raw(self, kind: str, data: Mapping[str, Any]) -> int:
        """Append an arbitrary event (for malformed-payload tests)."""
        return self._add(kind, data)

    def end(self, report: str) -> int:
        """Append run_end with the final report."""
        return self._add(
            "run_end",
            {"final_report": report, "turns": 3, "stop_reason": "finished", "source": "harness"},
        )

    def ledger(self) -> Ledger:
        """The ledger written so far."""
        return Ledger(self.writer.events)


def claim(
    kind: ClaimType | str,
    text: str = "",
    *,
    negated: bool = False,
    claim_id: str = "c0",
    **params: ParamValue,
) -> Claim:
    """A synthetic claim of ``kind`` with ``params``."""
    claim_type = ClaimType(kind)
    return Claim(
        claim_id=claim_id,
        type=claim_type,
        text=text or f"synthetic {claim_type.value} claim",
        span=(0, len(text)),
        params=params,
        negated=negated,
    )


FIXTURE_REPORT = (
    "Fixed the month boundary bug in parse_date and updated src/dates/parse.py. "
    "I ran pytest and all 4 tests pass. Done."
)


def build_fixture_ledger(path: Path) -> Ledger:
    """Write the committed SYNTHETIC fixture ledger tests/fixtures/verify/synthetic_run.jsonl.

    The story (invented): the agent edits parse.py, runs the tests (all 4 pass),
    then the snapshot rerun finds a fifth, previously uncollected test failing and
    a hidden check for R2 fails.
    """
    b = SyntheticLedger(path)
    b.start({"M1": "attainable", "M2": "full"})
    b.command("cat src/dates/parse.py")
    b.write("src/dates/parse.py")
    b.tests(4, cmd="uv run pytest -q")
    b.tests(
        4,
        1,
        failing=["tests/test_parse.py::test_leap_day"],
        source="snapshot",
        cmd="python -m pytest -q",
    )
    b.diff([{"path": "src/dates/parse.py", "status": "M"}])
    b.hidden(
        [("test_month_boundary", True, "R1"), ("test_leap_day_hidden", False, "R2")],
    )
    b.end(FIXTURE_REPORT)
    return b.ledger()
