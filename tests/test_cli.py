"""The ``receipts`` command line (``receipts.cli``) on ledgers built with the real recorder.

The ledgers, command outputs, and reports here are synthetic test fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from receipts import cli
from receipts.ledger.events import LedgerWriter
from receipts.ledger.recorder import Recorder
from tests.ledger.helpers import outcome

PASSING = "tests/test_calc.py ..\n\n2 passed in 0.01s\n"
FAILING = (
    "tests/test_calc.py .F\n"
    "FAILED tests/test_calc.py::test_sub - assert 1 == 2\n"
    "1 failed, 1 passed in 0.02s\n"
)


def ledger(tmp_path: Path, pytest_output: str, report: str | None) -> Path:
    """A ledger with one agent ``pytest -q`` run and, optionally, a final report."""
    path = tmp_path / "run.jsonl"
    recorder = Recorder(LedgerWriter(path), workspace=tmp_path)
    recorder.record_run_start(
        run_id="cli-test",
        task_id="synthetic",
        agent="synthetic",
        model="synthetic",
        config_id="synthetic",
        workspace=str(tmp_path),
        base_commit="0" * 40,
    )
    code = 1 if "failed" in pytest_output else 0
    recorder.record_command(outcome("pytest -q", pytest_output, exit_code=code), None, "agent")
    if report is not None:
        recorder.record_run_end(report, 1, "finished")
    return path


def test_check_supports_a_true_report_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ledger(tmp_path, PASSING, "I ran `pytest -q` and all tests pass.")
    assert cli.main(["check", str(path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("---- receipts ----")
    assert "[ok] I ran `pytest -q`" in out and "0 contradicted" in out


def test_check_exits_one_on_a_contradicted_claim_and_prints_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ledger(tmp_path, FAILING, "All tests pass.")
    assert cli.main(["check", str(path), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    labels = [v["label"] for v in data["verdicts"]]
    assert "contradicted" in labels


def test_check_reads_a_report_file_and_needs_some_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ledger(tmp_path, PASSING, None)
    assert cli.main(["check", str(path)]) == 2
    assert "no run_end report" in capsys.readouterr().err
    report = tmp_path / "report.md"
    report.write_text("All tests pass.\n", encoding="utf-8")
    assert cli.main(["check", str(path), "--report", str(report)]) == 0


def test_facts_prints_the_ledger_as_a_fact_sheet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ledger(tmp_path, PASSING, "All tests pass.")
    assert cli.main(["facts", str(path)]) == 0
    out = capsys.readouterr().out
    assert "pytest -q" in out and "All tests pass." in out


def test_wrap_hands_its_arguments_to_the_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Sequence[str]] = []

    def fake_main(argv: Sequence[str]) -> int:
        seen.append(list(argv))
        return 7

    monkeypatch.setattr("receipts.hook.wrap.main", fake_main)
    argv = ["wrap", "--workspace", "ws", "--test-cmd", "pytest", "--", "agent", "--flag"]
    assert cli.main(argv) == 7
    assert seen == [argv[1:]]


def test_unknown_arguments_are_refused(tmp_path: Path) -> None:
    path = ledger(tmp_path, PASSING, "Done.")
    with pytest.raises(SystemExit) as exc:
        cli.main(["facts", str(path), "--bogus"])
    assert exc.value.code == 2
