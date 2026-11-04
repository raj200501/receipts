import pytest
from pinwatch import PinwatchError, load_pins


def test_load_pins_reads_every_component(data_files):
    assert set(load_pins(data_files["pins"])) == {"gateway", "scheduler", "ledger"}


def test_load_pins_parses_versions(data_files):
    pins = load_pins(data_files["pins"])
    assert str(pins["gateway"]) == "1.4.2"
    assert pins["ledger"].prerelease == ("rc", "2")


def test_load_pins_accepts_a_leading_v(data_files):
    assert str(load_pins(data_files["pins"])["scheduler"]) == "0.9.1"


def test_load_pins_keeps_the_order_of_the_file(data_files):
    assert list(load_pins(data_files["pins"])) == ["gateway", "scheduler", "ledger"]


def test_load_pins_rejects_a_version_that_is_not_one(write_json):
    path = write_json("pins.json", {"components": {"gateway": "banana"}})
    with pytest.raises(PinwatchError, match="gateway: invalid version 'banana'"):
        load_pins(path)


def test_load_pins_rejects_a_number(write_json):
    path = write_json("pins.json", {"components": {"gateway": 1.4}})
    with pytest.raises(PinwatchError, match="version must be a string"):
        load_pins(path)


def test_load_pins_needs_a_components_object(write_json):
    with pytest.raises(PinwatchError, match="'components'"):
        load_pins(write_json("pins.json", ["gateway"]))


def test_load_pins_reports_a_missing_file(tmp_path):
    with pytest.raises(PinwatchError, match="cannot read"):
        load_pins(tmp_path / "missing.json")


def test_load_pins_reports_malformed_json(tmp_path):
    path = tmp_path / "pins.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PinwatchError, match="is not valid JSON"):
        load_pins(path)
