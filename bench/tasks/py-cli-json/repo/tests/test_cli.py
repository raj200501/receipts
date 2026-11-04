from pathlib import Path

import pytest
from stockctl.cli import main

TEXT = """sku,name,qty,unit_price,location,reorder_at,updated
A-1,Bolt,10,0.25,aisle-1,5,2026-01-01
A-2,Nut,3,0.10,aisle-1,5,2026-01-01
B-1,Gloves,8,3.75,dock,,2026-01-01
"""


@pytest.fixture
def stock(tmp_path: Path) -> str:
    path = tmp_path / "stock.csv"
    path.write_text(TEXT, encoding="utf-8")
    return str(path)


def test_list_prints_the_table(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", stock]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == [
        "A-1  Bolt     10  aisle-1",
        "A-2  Nut       3  aisle-1",
        "B-1  Gloves    8  dock",
    ]


def test_list_filters_by_location(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", stock, "--location", "dock"]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == ["B-1  Gloves    8  dock"]


def test_list_sorts_by_qty(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", stock, "--sort", "qty"]) == 0
    assert [line.split()[0] for line in capsys.readouterr().out.splitlines()[1:]] == [
        "A-1",
        "B-1",
        "A-2",
    ]


def test_low_prints_the_items_to_reorder(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["low", stock]) == 0
    assert capsys.readouterr().out == "A-2  Nut: 3 left, reorder at 5, short by 2\n"


def test_low_with_nothing_low(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["low", stock, "--location", "dock"]) == 0
    assert capsys.readouterr().out == "nothing to reorder\n"


def test_summary_prints_totals(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", stock]) == 0
    assert capsys.readouterr().out.splitlines()[:4] == [
        "items: 3",
        "units: 21",
        "low: 1",
        "value: 32.80",
    ]


def test_bad_row_exits_with_status_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(TEXT + "C-1,Tape,many,1.00,dock,,2026-01-01\n", encoding="utf-8")
    assert main(["list", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "stockctl: line 5: qty must be a whole number, got 'many'\n"


def test_missing_file_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["summary", str(tmp_path / "nope.csv")]) == 2
    assert capsys.readouterr().err.startswith("stockctl: cannot read ")


def test_example_file_is_readable(capsys: pytest.CaptureFixture[str]) -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "stock.csv"
    assert main(["summary", str(example)]) == 0
    assert capsys.readouterr().out.startswith("items: 8\n")
