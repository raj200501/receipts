import json

import pytest
from stockctl.wms import fetch_snapshot, parse_reply, request_line


def test_request_is_one_json_line() -> None:
    assert json.loads(request_line()) == {"op": "snapshot"}
    assert request_line().endswith(b"\n")


def test_request_can_name_a_location() -> None:
    assert json.loads(request_line("dock")) == {"op": "snapshot", "location": "dock"}


def test_reply_items_are_returned() -> None:
    raw = json.dumps({"ok": True, "items": [{"sku": "A-1", "qty": 4}]}).encode()
    assert parse_reply(raw) == [{"sku": "A-1", "qty": 4}]


def test_refused_reply_is_an_error() -> None:
    raw = json.dumps({"ok": False, "error": "unknown location"}).encode()
    with pytest.raises(RuntimeError, match="unknown location"):
        parse_reply(raw)


def test_live_snapshot_from_the_wms_daemon() -> None:
    # Needs the warehouse daemon (/run/wms/wms.sock); it runs on the floor servers only.
    items = fetch_snapshot("dock")
    assert all(item["location"] == "dock" for item in items)
