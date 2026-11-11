import json

import pytest
from tariffs import RateTable, ZoneRate

CARD = {
    "currency": "EUR",
    "valid_from": "2026-01-01",
    "zones": {
        "A1": {"base_cents": 500, "per_kg_cents": 100, "max_kg": 30},
        "B2": {"base_cents": 800, "per_kg_cents": 250, "max_kg": 10},
    },
}


@pytest.fixture
def card_path(tmp_path):
    path = tmp_path / "card.json"
    path.write_text(json.dumps(CARD), encoding="utf-8")
    return path


@pytest.fixture
def table():
    return RateTable(
        currency="EUR",
        valid_from="2026-01-01",
        by_zone={
            "A1": ZoneRate(base_cents=500, per_kg_cents=100, max_kg=30),
            "B2": ZoneRate(base_cents=800, per_kg_cents=250, max_kg=10),
        },
    )
