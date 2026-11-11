from pathlib import Path

import pytest
from invoicer.cli import main

ROWS = """invoice,customer,description,quantity,unit_price,vat_rate
INV-1,Harbor Street Bakery,Espresso machine service,1,185.00,20
INV-2,Linden Dental Practice,Printer paper A4 (ream),12,4.35,20
"""


def _export(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "export.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_totals_prints_every_invoice(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["totals", str(_export(tmp_path, ROWS))]) == 0
    out = capsys.readouterr().out
    assert out.startswith("INV-1  Harbor Street Bakery\n")
    assert "\nINV-2  Linden Dental Practice\n" in out


def test_totals_prints_one_invoice(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["totals", str(_export(tmp_path, ROWS)), "--invoice", "INV-2"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "INV-2  Linden Dental Practice"
    assert "INV-1" not in out


def test_unknown_invoice_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["totals", str(_export(tmp_path, ROWS)), "--invoice", "INV-9"]) == 2
    assert "no invoice INV-9" in capsys.readouterr().err


def test_list_prints_the_totals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", str(_export(tmp_path, ROWS))]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "INV-1           Harbor Street Bakery              222.00",
        "INV-2           Linden Dental Practice             62.64",
    ]


def test_missing_file_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["totals", str(tmp_path / "missing.csv")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_bad_row_exits_with_status_2_and_names_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, ROWS + "INV-3,Kestrel Cycles,Delivery,1,seven,20\n")
    assert main(["list", str(path)]) == 2
    assert capsys.readouterr().err.startswith("invoicer: line 4: invalid unit price")
