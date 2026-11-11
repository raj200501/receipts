import json

import pytest
from tariffs.cli import main


@pytest.fixture
def eu_card(tmp_path):
    zone = {"base_cents": 500, "per_kg_cents": 100, "max_kg": 30}
    path = tmp_path / "eu.json"
    path.write_text(json.dumps({"currency": "EUR", "zones": {"EU1": zone}}), encoding="utf-8")
    return path


def test_quote_prints_the_price(eu_card, capsys):
    assert main(["quote", "--rates", str(eu_card), "--country", "DE", "--weight", "2.5"]) == 0
    assert capsys.readouterr().out == "8.00 EUR\n"


def test_quote_accepts_a_lowercase_country(eu_card, capsys):
    assert main(["quote", "--rates", str(eu_card), "--country", "fr", "--weight", "1"]) == 0
    assert capsys.readouterr().out == "6.00 EUR\n"


def test_quote_for_an_unknown_country_is_an_error(eu_card, capsys):
    assert main(["quote", "--rates", str(eu_card), "--country", "ZZ", "--weight", "1"]) == 2
    assert "tariffs: error: unknown country 'ZZ'" in capsys.readouterr().err


def test_quote_for_an_overweight_parcel_is_an_error(eu_card, capsys):
    assert main(["quote", "--rates", str(eu_card), "--country", "DE", "--weight", "31"]) == 2
    assert "above the 30 kg limit" in capsys.readouterr().err


def test_zones_prints_one_line_per_zone(card_path, capsys):
    assert main(["zones", "--rates", str(card_path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "A1: 5.00 EUR + 1.00 EUR/kg, up to 30 kg",
        "B2: 8.00 EUR + 2.50 EUR/kg, up to 10 kg",
    ]


def test_a_missing_rate_file_is_a_usage_error(tmp_path, capsys):
    assert main(["zones", "--rates", str(tmp_path / "nope.json")]) == 2
    assert "tariffs: error: cannot read rate file" in capsys.readouterr().err


def test_a_missing_command_is_a_usage_error(capsys):
    assert main([]) == 2
    assert capsys.readouterr().err


def test_a_weight_that_is_not_a_number_is_a_usage_error(card_path, capsys):
    argv = ["quote", "--rates", str(card_path), "--country", "DE", "--weight", "heavy"]
    assert main(argv) == 2
    assert capsys.readouterr().err
