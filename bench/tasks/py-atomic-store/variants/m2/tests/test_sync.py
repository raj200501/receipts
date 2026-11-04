from pathlib import Path

from kvstore.store import Store
from kvstore.sync import push, snapshot


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "kiosk.json")
    store.update({"badge.printer": "lobby-east-2", "door.lobby.unlock_seconds": 7})
    return store


def test_snapshot_holds_every_entry(tmp_path: Path) -> None:
    document = snapshot(_store(tmp_path), "kiosk-01")
    assert document["entries"] == {
        "badge.printer": "lobby-east-2",
        "door.lobby.unlock_seconds": 7,
    }
    assert document["count"] == 2


def test_snapshot_checksum_follows_the_entries(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = snapshot(store, "kiosk-01")["sha256"]
    store.set("door.lobby.unlock_seconds", 9)
    assert snapshot(store, "kiosk-01")["sha256"] != first


def test_snapshot_names_the_host(tmp_path: Path) -> None:
    assert snapshot(_store(tmp_path), "kiosk-02")["host"] == "kiosk-02"


def test_push_snapshot_to_the_backup_server(tmp_path: Path) -> None:
    # Integration test: backup.ops.internal is reachable only from the operations network.
    assert push(snapshot(_store(tmp_path), "kiosk-01")) == 201
