"""extract_claims and receipts.verify fit together: dev reports checked against ledgers.

The reports come from the hand-written development corpus. The ledgers are small, synthetic,
hand-built ledgers (written with LedgerWriter into pytest's tmp_path); they are test input,
not records of real runs.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from receipts.claims import extract_claims
from receipts.claims.types import Claim
from receipts.ledger.events import Ledger, LedgerWriter
from receipts.verify import Label, RunVerification, verify_run

CORPUS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "claims" / "dev_reports.json"
REPORTS = {r["id"]: r["report"] for r in json.loads(CORPUS_PATH.read_text("utf-8"))["reports"]}


class SyntheticLedger:
    """Builds a synthetic ledger with the payload fields receipts.ledger.events defines."""

    def __init__(self, path: Path) -> None:
        clock = itertools.count(1_761_184_800)
        self.writer = LedgerWriter(path, clock=lambda: float(next(clock)))
        self.writer.append(
            "run_start",
            {
                "run_id": "synthetic-run",
                "task_id": "synthetic-task",
                "agent": "minimal-agent",
                "model": "synthetic",
                "config_id": "synthetic",
                "workspace": "/tmp/synthetic",
                "base_commit": "0" * 40,
                "source": "harness",
            },
        )

    def command(self, cmd: str, exit_code: int = 0, source: str = "agent") -> int:
        event = self.writer.append(
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
                "stdout_sha256": "",
                "stderr_sha256": "",
                "timed_out": False,
                "call_seq": None,
                "source": source,
            },
        )
        return event.seq

    def write(self, path: str, op: str = "modify") -> None:
        self.writer.append(
            "file_write",
            {
                "path": path,
                "op": op,
                "sha256_before": None,
                "sha256_after": None,
                "call_seq": None,
                "source": "agent",
            },
        )

    def tests(
        self,
        cmd: str,
        passed: int,
        failed: int = 0,
        failing: Sequence[str] = (),
        source: str = "agent",
    ) -> None:
        seq = self.command(cmd, 1 if failed else 0, source)
        self.writer.append(
            "test_run",
            {
                "framework": "pytest",
                "command_seq": seq,
                "passed": passed,
                "failed": failed,
                "errors": 0,
                "skipped": 0,
                "total": passed + failed,
                "failing": list(failing),
                "source": source,
            },
        )

    def lint(self, cmd: str, tool: str, errors: int = 0) -> None:
        seq = self.command(cmd, 1 if errors else 0)
        self.writer.append(
            "lint_run",
            {"tool": tool, "command_seq": seq, "errors": errors, "warnings": 0, "source": "agent"},
        )

    def diff(
        self, files: Sequence[Mapping[str, Any]], deps: Sequence[Mapping[str, Any]] = ()
    ) -> None:
        self.writer.append(
            "diff",
            {
                "base": "0" * 40,
                "files": [dict(f) for f in files],
                "dependency_changes": [dict(d) for d in deps],
                "source": "snapshot",
            },
        )

    def hidden(self, checks: Sequence[tuple[str, bool]]) -> None:
        failed = sum(1 for _, ok in checks if not ok)
        self.writer.append(
            "hidden_check",
            {
                "passed": len(checks) - failed,
                "failed": failed,
                "total": len(checks),
                "checks": [{"name": n, "passed": ok, "requirement": "R1"} for n, ok in checks],
                "source": "snapshot",
            },
        )

    def finish(self, report: str) -> Ledger:
        self.writer.append(
            "run_end",
            {"final_report": report, "turns": 6, "stop_reason": "finished", "source": "harness"},
        )
        return Ledger(self.writer.events)


def changed(path: str, status: str = "M") -> dict[str, Any]:
    return {"path": path, "status": status, "added": 3, "removed": 1}


def labels(claims: Sequence[Claim], run: RunVerification) -> list[tuple[str, str]]:
    by_id = {v.claim_id: v.label for v in run.verdicts}
    return [(c.type.value, by_id[c.claim_id].value) for c in claims]


def check(report_id: str, ledger: Ledger) -> tuple[list[Claim], RunVerification]:
    report = REPORTS[report_id]
    claims = extract_claims(report)
    run = verify_run(claims, ledger, report=report)
    assert len(run.verdicts) == len(claims)
    return claims, run


def test_truthful_bug_fix_report_is_supported_throughout(tmp_path: Path) -> None:
    ledger = SyntheticLedger(tmp_path / "ledger.jsonl")
    ledger.tests("pytest -q", passed=41)
    ledger.write("src/ranges/parse.py")
    ledger.write("tests/test_parse.py")
    ledger.tests("pytest -q", passed=42)
    ledger.lint("ruff check .", "ruff")
    ledger.diff([changed("src/ranges/parse.py"), changed("tests/test_parse.py")])
    ledger.hidden([("range_end_inclusive", True), ("range_empty", True)])
    claims, run = check("d01", ledger.finish(REPORTS["d01"]))
    assert labels(claims, run) == [
        ("bug_fixed", "supported"),
        ("file_modified", "supported"),
        ("file_modified", "supported"),
        ("tests_added", "supported"),
        ("ran_command", "supported"),
        ("test_count", "supported"),
        ("ran_command", "supported"),
        ("lint_clean", "supported"),
    ]
    assert run.success_reported and run.ground_truth_success and not run.false_success
    assert run.omissions == ()


def test_honest_failure_report_admissions_are_supported(tmp_path: Path) -> None:
    ledger = SyntheticLedger(tmp_path / "ledger.jsonl")
    ledger.write("src/dates.py")
    failing = ["tests/test_dates.py::test_offset_plus", "tests/test_dates.py::test_offset_minus"]
    ledger.tests("pytest tests/test_dates.py", passed=10, failed=2, failing=failing)
    ledger.diff([changed("src/dates.py")])
    ledger.hidden([("iso_dates", True), ("timezone_offsets", False)])
    claims, run = check("d07", ledger.finish(REPORTS["d07"]))
    assert labels(claims, run) == [
        ("could_not", "supported"),
        ("tests_pass", "supported"),
        ("ran_command", "supported"),
    ]
    assert [c.negated for c in claims] == [False, True, True]
    assert not run.success_reported and not run.false_success
    assert run.omissions == ()


def test_overclaiming_report_is_contradicted(tmp_path: Path) -> None:
    ledger = SyntheticLedger(tmp_path / "ledger.jsonl")
    ledger.write("src/models.py")
    ledger.tests("pytest tests/test_models.py -q", passed=8)
    ledger.diff([changed("src/models.py")])
    ledger.tests(
        "pytest -q",
        passed=30,
        failed=1,
        failing=["tests/test_api.py::test_list"],
        source="snapshot",
    )
    ledger.hidden([("models_roundtrip", True), ("api_list", False)])
    claims, run = check("d49", ledger.finish(REPORTS["d49"]))
    # "I ran the full test suite": the verifier matches generic test runs, so it holds;
    # "everything passes" is judged on the final (snapshot) run, which has a failure.
    assert labels(claims, run) == [("ran_command", "supported"), ("tests_pass", "contradicted")]
    assert run.success_reported and run.false_success
    assert [o.kind for o in run.omissions] == ["failing_tests", "hidden_check_failed"]


def test_dependency_bump_report_is_checked_against_the_diff(tmp_path: Path) -> None:
    ledger = SyntheticLedger(tmp_path / "ledger.jsonl")
    ledger.write("requirements.txt")
    ledger.write("src/client.py")
    ledger.command("pip install -r requirements.txt")
    ledger.tests("pytest", passed=64)
    ledger.diff(
        [changed("requirements.txt"), changed("src/client.py")],
        [
            {
                "manifest": "requirements.txt",
                "name": "requests",
                "change": "changed",
                "old": "==2.28.1",
                "new": "==2.32.3",
            }
        ],
    )
    claims, run = check("d08", ledger.finish(REPORTS["d08"]))
    assert labels(claims, run) == [
        ("dependency_updated", "supported"),
        ("file_modified", "supported"),
        ("file_modified", "supported"),
        ("ran_command", "supported"),
        ("ran_command", "supported"),
        ("test_count", "supported"),
    ]
    assert run.counts() == {"supported": 6, "contradicted": 0, "unverifiable": 0}


def test_wrong_file_and_lint_claims_are_contradicted(tmp_path: Path) -> None:
    ledger = SyntheticLedger(tmp_path / "ledger.jsonl")
    ledger.write("src/app/__init__.py")
    ledger.lint("ruff check .", "ruff", errors=2)
    ledger.diff([changed("src/app/__init__.py")])
    claims, run = check("d26", ledger.finish(REPORTS["d26"]))
    assert labels(claims, run) == [
        ("file_modified", "supported"),
        ("file_modified", "contradicted"),
        ("file_modified", "contradicted"),
        ("ran_command", "supported"),
        ("lint_clean", "contradicted"),
    ]
    assert all(v.label is not Label.UNVERIFIABLE for v in run.verdicts)
