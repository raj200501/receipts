import json

from pinwatch.fleet import payload, publish


def test_payload_has_one_line_per_component():
    lines = payload({"gateway": "1.4.2", "ledger": "2.1.0-rc.2"}).decode().splitlines()
    assert len(lines) == 2


def test_payload_is_sorted_by_component():
    lines = payload({"ledger": "2.1.0-rc.2", "gateway": "1.4.2"}).decode().splitlines()
    assert [json.loads(line)["component"] for line in lines] == ["gateway", "ledger"]


def test_payload_of_no_pins_is_empty():
    assert payload({}) == b""


def test_publish_pins_to_fleet_inventory():
    # Needs fleetd on /run/fleetd/inventory.sock, which exists only on the deploy hosts.
    assert publish({"gateway": "1.4.2", "ledger": "2.1.0-rc.2"}) == "ok"
