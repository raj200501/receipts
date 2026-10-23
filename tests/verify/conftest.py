"""Fixtures for the verifier tests (all ledgers are synthetic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.verify.ledgers import SyntheticLedger


@pytest.fixture
def lb(tmp_path: Path) -> SyntheticLedger:
    """A fresh synthetic ledger builder writing to tmp_path."""
    return SyntheticLedger(tmp_path / "ledger.jsonl")
