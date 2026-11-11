import json

import pytest
from tariffs import RateFileError, UnknownZoneError, ZoneRate, load_rates


def test_a_rate_file_is_loaded(card_path):
    loaded = load_rates(card_path)
    assert loaded.currency == "EUR"
    assert loaded.valid_from == "2026-01-01"
    assert loaded.rate("A1") == ZoneRate(base_cents=500, per_kg_cents=100, max_kg=30)


def test_the_path_may_be_text_or_a_path(card_path):
    assert load_rates(str(card_path)).zones == load_rates(card_path).zones


def test_zones_are_listed_in_sorted_order(card_path):
    assert load_rates(card_path).zones == ["A1", "B2"]


def test_the_currency_defaults_to_euro(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"zones": {}}), encoding="utf-8")
    assert load_rates(path).currency == "EUR"


def test_an_unknown_zone_raises_unknown_zone_error(table):
    with pytest.raises(UnknownZoneError, match="unknown zone 'C3'"):
        table.rate("C3")


def test_a_missing_file_raises_rate_file_error(tmp_path):
    with pytest.raises(RateFileError, match="cannot read rate file"):
        load_rates(tmp_path / "nope.json")


def test_a_file_that_is_not_json_raises_rate_file_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("zones: none", encoding="utf-8")
    with pytest.raises(RateFileError, match="not valid JSON"):
        load_rates(path)


def test_a_file_without_zones_raises_rate_file_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"currency": "EUR"}), encoding="utf-8")
    with pytest.raises(RateFileError, match="no 'zones' object"):
        load_rates(path)


def test_a_zone_with_a_missing_amount_raises_rate_file_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"zones": {"A1": {"base_cents": 5}}}), encoding="utf-8")
    with pytest.raises(RateFileError, match="zone A1: missing per_kg_cents"):
        load_rates(path)


@pytest.mark.parametrize("amount", [0, -5, 1.5, "7", True])
def test_amounts_must_be_positive_whole_numbers(tmp_path, amount):
    zone = {"base_cents": amount, "per_kg_cents": 100, "max_kg": 30}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"zones": {"A1": zone}}), encoding="utf-8")
    with pytest.raises(RateFileError, match="positive whole numbers"):
        load_rates(path)


def test_rate_file_error_is_a_value_error():
    assert issubclass(RateFileError, ValueError)
