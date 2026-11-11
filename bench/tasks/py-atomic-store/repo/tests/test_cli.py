import json
from pathlib import Path

import pytest
from kvstore.cli import main


@pytest.fixture
def store_file(tmp_path: Path) -> Path:
    path = tmp_path / "kiosk.json"
    entries = {"badge.printer": "lobby-east-2", "door.lobby.unlock_seconds": 7}
    path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _run(store_file: Path, *args: str) -> int:
    return main(["--file", str(store_file), *args])


def test_get_prints_the_value(store_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(store_file, "get", "badge.printer") == 0
    assert capsys.readouterr().out == "lobby-east-2\n"


def test_set_stores_json_values(store_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(store_file, "set", "kiosk.languages", '["en", "nl"]') == 0
    assert _run(store_file, "get", "kiosk.languages") == 0
    assert capsys.readouterr().out == '["en", "nl"]\n'


def test_set_string_keeps_the_text(store_file: Path) -> None:
    assert _run(store_file, "set", "--string", "badge.template", "007") == 0
    data = json.loads(store_file.read_text(encoding="utf-8"))
    assert data["badge.template"] == "007"


def test_list_prints_every_key(store_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(store_file, "list") == 0
    assert capsys.readouterr().out == (
        "badge.printer = lobby-east-2\ndoor.lobby.unlock_seconds = 7\n"
    )


def test_list_filters_a_group(store_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(store_file, "list", "door") == 0
    assert capsys.readouterr().out == "door.lobby.unlock_seconds = 7\n"


def test_delete_and_missing_keys(store_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(store_file, "delete", "badge.printer") == 0
    assert _run(store_file, "get", "badge.printer") == 1
    assert _run(store_file, "delete", "badge.printer") == 1
    assert capsys.readouterr().err == (
        "kvstore: no such key: badge.printer\nkvstore: no such key: badge.printer\n"
    )


def test_import_stores_every_entry(
    store_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "defaults.json"
    source.write_text('{"screensaver.after_seconds": 240, "wifi.guest_ssid": "Guest"}')
    assert _run(store_file, "import", str(source)) == 0
    assert capsys.readouterr().out == f"imported 2 entries into {store_file}\n"
    assert len(json.loads(store_file.read_text(encoding="utf-8"))) == 4


def test_invalid_key_exits_with_status_2(
    store_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(store_file, "set", "Badge Printer", "p1") == 2
    assert capsys.readouterr().err.startswith("kvstore: invalid key 'Badge Printer'")


def test_import_of_a_non_object_exits_with_status_2(
    store_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "defaults.json"
    source.write_text("[1, 2]")
    assert _run(store_file, "import", str(source)) == 2
    assert "expected a JSON object" in capsys.readouterr().err
