from pathlib import Path

import pytest
from unitconv.cli import main


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    status = main(list(argv))
    out, err = capsys.readouterr()
    return status, out, err


def test_convert_prints_the_conversion(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "convert", "12", "ft", "m") == (0, "12 ft = 3.6576 m\n", "")


def test_convert_accepts_unit_names(capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run(capsys, "convert", "5.5", "pounds", "kilograms", "--precision", "2")
    assert (status, out) == (0, "5.5 lb = 2.49 kg\n")


def test_convert_temperature(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "convert", "-40", "celsius", "F") == (0, "-40 C = -40 F\n", "")


def test_convert_unknown_unit_exits_with_status_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "convert", "1", "furlong", "m") == (
        2,
        "",
        "unitconv: unknown unit 'furlong'\n",
    )


def test_convert_mismatched_units_exit_with_status_2(capsys: pytest.CaptureFixture[str]) -> None:
    status, out, err = run(capsys, "convert", "3", "feet", "kg")
    assert (status, out) == (2, "")
    assert err == "unitconv: cannot convert length (ft) to mass (kg)\n"


def test_convert_rejects_a_value_that_is_not_a_number(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(capsys, "convert", "abc", "m", "ft") == (2, "", "unitconv: not a number: 'abc'\n")


def test_batch_converts_every_line(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = tmp_path / "weights.txt"
    path.write_text("# parcels for route 7\n12 lb\n\n3.5kg\n40 oz\n", encoding="utf-8")
    status, out, _ = run(capsys, "batch", str(path), "--to", "kg")
    assert status == 0
    assert out.splitlines() == ["12 lb = 5.4431 kg", "3.5 kg = 3.5 kg", "40 oz = 1.134 kg"]


def test_batch_stops_at_a_bad_line(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = tmp_path / "weights.txt"
    path.write_text("12 lb\n3.5 kg\n2 pallets\n", encoding="utf-8")
    assert run(capsys, "batch", str(path), "--to", "kg") == (
        2,
        "",
        "unitconv: line 3: unknown unit 'pallets'\n",
    )


def test_batch_reports_a_missing_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    status, out, err = run(capsys, "batch", str(tmp_path / "missing.txt"), "--to", "kg")
    assert (status, out) == (2, "")
    assert err.startswith("unitconv: no such file:")
