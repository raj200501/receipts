import json
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


def test_list_json_is_an_array_of_items(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", stock, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [item["sku"] for item in data] == ["A-1", "A-2", "B-1"]
    assert data[2] == {
        "sku": "B-1",
        "name": "Gloves",
        "qty": 8,
        "unit_price": "3.75",
        "location": "dock",
        "reorder_at": None,
        "updated": "2026-01-01",
    }


def test_list_json_honors_location_and_sort(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", stock, "--location", "aisle-1", "--sort", "qty", "--json"]) == 0
    assert [item["sku"] for item in json.loads(capsys.readouterr().out)] == ["A-1", "A-2"]


def test_list_json_of_nothing_is_an_empty_array(
    stock: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list", stock, "--location", "roof", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_low_json_adds_short_by(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["low", stock, "--json"]) == 0
    (item,) = json.loads(capsys.readouterr().out)
    assert (item["sku"], item["short_by"], item["unit_price"]) == ("A-2", 2, "0.10")


def test_summary_json(stock: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", stock, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "items": 3,
        "units": 21,
        "low": 1,
        "value": "32.80",
        "locations": {"aisle-1": 13, "dock": 8},
    }


def test_json_error_names_the_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(TEXT + "C-1,Tape,many,1.00,dock,,2026-01-01\n", encoding="utf-8")
    assert main(["list", str(path), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": "qty must be a whole number, got 'many'",
        "line": 5,
    }


def test_json_error_for_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", str(tmp_path / "nope.csv"), "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["line"] is None
    assert error["error"].startswith("cannot read ")
