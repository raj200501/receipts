from pathlib import Path

import pytest
from invoicer.cli import main

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "october.csv"
HEADER = "invoice,customer,description,quantity,unit_price,vat_rate\n"


def test_half_cent_line_rounds_to_the_even_cent(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["totals", str(EXAMPLE), "--invoice", "INV-2026-1044"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "INV-2026-1044  Kestrel Cycles",
        "  Chain lube sachets                  2.68",
        "  Workshop rags (kg)                  8.40",
        "  subtotal                           11.08",
        "  vat 20%                             2.22",
        "  total                              13.30",
    ]


def test_half_cent_vat_rounds_to_the_even_cent(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["totals", str(EXAMPLE), "--invoice", "INV-2026-1045"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "  vat 5.5%                            1.04" in lines
    assert "  vat 7%                              0.52" in lines
    assert lines[-1] == "  total                              28.06"


@pytest.mark.parametrize("command", ["totals", "list"])
def test_nan_unit_price_stops_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    path = tmp_path / "export.csv"
    path.write_text(HEADER + "INV-1,A,Paper,1,4.35,20\nINV-1,A,Maps,1,NaN,20\n", encoding="utf-8")
    assert main([command, str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.err == "invoicer: line 3: invalid unit price 'NaN'\n"
    assert captured.out == ""
