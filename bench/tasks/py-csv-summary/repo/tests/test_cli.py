from pathlib import Path

import pytest
from csvsummary.cli import main

ROWS = """order,customer,city,total
A-1,Ruth Iyer,Lisbon,12.50
A-2,Jonas Berg,Porto,8.00
A-3,Ruth Iyer,Porto,30.25
"""


def _file(tmp_path: Path, text: str = ROWS) -> Path:
    path = tmp_path / "orders.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_summary_prints_rows_and_columns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["summary", str(_file(tmp_path))]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["rows: 3", "columns: 4"]
    assert lines[-1] == "total          3         3  8.00        30.25       16.92"


def test_top_prints_the_most_common_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["top", str(_file(tmp_path)), "city"]) == 0
    assert capsys.readouterr().out == "     2  Porto\n     1  Lisbon\n"


def test_top_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["top", str(_file(tmp_path)), "customer", "--limit", "1"]) == 0
    assert capsys.readouterr().out == "     2  Ruth Iyer\n"


def test_delimiter_option(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _file(tmp_path, "order;total\nA-1;3\nA-2;5\n")
    assert main(["summary", str(path), "--delimiter", ";"]) == 0
    assert capsys.readouterr().out.splitlines()[-1].split() == ["total", "2", "2", "3", "5", "4.00"]


def test_tab_delimiter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _file(tmp_path, "order\ttotal\nA-1\t3\n")
    assert main(["top", str(path), "order", "--delimiter", "tab"]) == 0
    assert capsys.readouterr().out == "     1  A-1\n"


def test_missing_file_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["summary", str(tmp_path / "missing.csv")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_bad_row_exits_with_status_2_and_names_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _file(tmp_path, ROWS + "A-4,Mei Tanaka,Braga,9.00,extra\n")
    assert main(["summary", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"csvsummary: {path}: line 5: expected at most 4 fields, got 5\n"


def test_unknown_column_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["top", str(_file(tmp_path)), "region"]) == 2
    assert "no column named 'region'" in capsys.readouterr().err


def test_limit_must_be_at_least_one(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["top", str(_file(tmp_path)), "city", "--limit", "0"])
    assert stopped.value.code == 2
