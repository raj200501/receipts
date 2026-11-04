import json
from pathlib import Path

import pytest
from kvstore.keys import KeyRuleError
from kvstore.store import Store, StoreError


def test_missing_file_is_an_empty_store(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.json")
    assert len(store) == 0
    assert store.keys() == []
    assert not (tmp_path / "store.json").exists()


def test_set_writes_the_file(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    Store(path).set("badge.printer", "lobby-east-2")
    assert json.loads(path.read_text(encoding="utf-8")) == {"badge.printer": "lobby-east-2"}


def test_file_has_sorted_keys_an_indent_and_a_final_newline(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    store = Store(path)
    store.set("kiosk.welcome", "Hello")
    store.set("door.lobby.unlock_seconds", 7)
    assert path.read_text(encoding="utf-8") == (
        '{\n  "door.lobby.unlock_seconds": 7,\n  "kiosk.welcome": "Hello"\n}\n'
    )


def test_values_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    Store(path).update({"kiosk.languages": ["en", "nl"], "sign_in.notify_host": True})
    store = Store(path)
    assert store.get("kiosk.languages") == ["en", "nl"]
    assert store["sign_in.notify_host"] is True


def test_get_returns_the_default_for_missing_keys(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.json")
    assert store.get("badge.printer") is None
    assert store.get("badge.printer", "none") == "none"
    with pytest.raises(KeyError):
        store["badge.printer"]


def test_keys_and_items_are_sorted_and_filtered(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.json")
    store.update({"kiosk.welcome": "Hi", "badge.printer": "p1", "kiosk.languages": ["en"]})
    assert store.keys() == ["badge.printer", "kiosk.languages", "kiosk.welcome"]
    assert store.items("kiosk") == [("kiosk.languages", ["en"]), ("kiosk.welcome", "Hi")]


def test_delete_removes_a_key(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    store = Store(path)
    store.update({"a.one": 1, "a.two": 2})
    store.delete("a.one")
    assert Store(path).keys() == ["a.two"]
    with pytest.raises(KeyError):
        store.delete("a.one")


def test_invalid_keys_are_rejected_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    store = Store(path)
    with pytest.raises(KeyRuleError):
        store.set("Badge Printer", "p1")
    with pytest.raises(KeyRuleError):
        store.update({"ok.key": 1, "not ok": 2})
    assert not path.exists()


def test_a_file_that_is_not_an_object_is_a_store_error(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text('["badge.printer"]\n', encoding="utf-8")
    with pytest.raises(StoreError, match="expected a JSON object"):
        Store(path)


def test_rewriting_keeps_the_other_entries(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    Store(path).update({"a.one": 1, "a.two": 2})
    Store(path).set("a.one", 10)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a.one": 10, "a.two": 2}
