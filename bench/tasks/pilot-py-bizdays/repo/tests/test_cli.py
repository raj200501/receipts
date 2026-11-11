import json
from pathlib import Path

import pytest
from bizdays.cli import main


@pytest.fixture
def config(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    days = {"2026-12-24": "Winter closure", "2026-12-25": "Winter closure"}
    (data / "closures.json").write_text(json.dumps({"days": days}), encoding="utf-8")
    path = tmp_path / "config" / "calendar.toml"
    path.parent.mkdir()
    path.write_text('[calendar]\nsource = "data/closures.json"\n', encoding="utf-8")
    return path


def test_add_prints_the_date(config: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(config), "add", "2026-12-23", "1"]) == 0
    assert capsys.readouterr().out == "2026-12-28\n"


def test_check_reports_closure_days(config: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(config), "check", "2026-12-24"]) == 0
    assert capsys.readouterr().out == "2026-12-24 is not a business day\n"


def test_check_reports_business_days(config: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(config), "check", "2026-12-23"]) == 0
    assert "is a business day" in capsys.readouterr().out


def test_unloadable_calendar_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(tmp_path / "missing.toml"), "add", "2026-12-23", "1"]) == 2
    assert capsys.readouterr().err.startswith("bizdays: configuration file not found")


def test_invalid_date_is_a_usage_error(config: Path) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--config", str(config), "add", "23.12.2026", "1"])
    assert info.value.code == 2
