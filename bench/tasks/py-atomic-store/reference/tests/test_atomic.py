import resource
import signal
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from kvstore.cli import main
from kvstore.store import Store, StoreError, StoreWriteError

ENTRIES = {"badge.printer": "lobby-east-2", "door.lobby.unlock_seconds": 7}


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "kiosk.json"
    Store(path).update(ENTRIES)
    return path


def _files(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


@contextmanager
def _full_disk(limit: int) -> Iterator[None]:
    """Writes past ``limit`` bytes fail with EFBIG, as they do on a full disk."""
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    previous = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))
    try:
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
        signal.signal(signal.SIGXFSZ, previous)


def test_value_that_is_not_json_changes_nothing(tmp_path: Path) -> None:
    path = _store(tmp_path)
    before = path.read_bytes()
    store = Store(path)
    with pytest.raises(TypeError):
        store.set("zz.logo", object())
    with pytest.raises(TypeError):
        store.update({"kiosk.welcome": "Hi", "zz.logo": {1, 2}})
    assert path.read_bytes() == before
    assert store.items() == sorted(ENTRIES.items())
    assert _files(tmp_path) == ["kiosk.json"]


def test_full_disk_changes_nothing(tmp_path: Path) -> None:
    path = _store(tmp_path)
    before = path.read_bytes()
    store = Store(path)
    with _full_disk(len(before) + 64), pytest.raises(StoreWriteError, match="could not write"):
        store.set("kiosk.welcome", "x" * 20000)
    assert path.read_bytes() == before
    assert store.get("kiosk.welcome") is None
    assert _files(tmp_path) == ["kiosk.json"]
    store.set("kiosk.welcome", "Welcome")
    assert Store(path).get("kiosk.welcome") == "Welcome"


def test_failed_write_exits_with_status_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _store(tmp_path)
    before = path.read_bytes()
    with _full_disk(len(before) + 64):
        status = main(["--file", str(path), "set", "kiosk.welcome", "x" * 20000])
    assert status == 1
    assert capsys.readouterr().err.startswith(f"kvstore: could not write {path}")
    assert path.read_bytes() == before


def test_rewrite_keeps_the_permission_bits(tmp_path: Path) -> None:
    path = _store(tmp_path)
    path.chmod(0o640)
    Store(path).set("kiosk.welcome", "Welcome")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.parametrize("text", ['{\n  "badge.printer": "lobby-ea', '{\n  "a.b": 9', ""])
def test_damaged_file_is_a_store_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "kiosk.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(StoreError, match=r"kiosk\.json is damaged"):
        Store(path)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("args", [["get", "a.b"], ["set", "a.b", "1"], ["delete", "a.b"], ["list"]])
def test_damaged_file_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    path = tmp_path / "kiosk.json"
    path.write_text('{\n  "a.b": 9', encoding="utf-8")
    assert main(["--file", str(path), *args]) == 2
    assert "kiosk.json is damaged" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == '{\n  "a.b": 9'
