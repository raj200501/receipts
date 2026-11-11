from pathlib import Path

import pytest
from timesheet.cli import main

ROWS = """date,start,end,project,note
2026-03-02,09:00,12:00,billing,
2026-03-03,13:00,14:30,support,
"""


def _file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "entries.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_report_prints_weekly_totals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", str(_file(tmp_path, ROWS))]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "2026-W10"
    assert "  total           4:30" in out


def test_report_filters_a_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", str(_file(tmp_path, ROWS)), "--project", "billing"]) == 0
    assert "support" not in capsys.readouterr().out


def test_missing_file_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", str(tmp_path / "missing.csv")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_bad_row_exits_with_status_2_and_names_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _file(tmp_path, ROWS + "2026-03-04,09:00,noon,admin,\n")
    assert main(["report", str(path)]) == 2
    assert capsys.readouterr().err.startswith("timesheet: line 4:")
