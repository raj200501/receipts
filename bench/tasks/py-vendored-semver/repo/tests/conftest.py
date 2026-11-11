"""Shared fixtures: small data files written to a temporary directory."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

PINS = {"gateway": "1.4.2", "scheduler": "v0.9.1", "ledger": "2.1.0-rc.2"}
RELEASES = {
    "gateway": ["1.4.0", "1.4.2", "1.5.0", "2.0.0-rc.1"],
    "scheduler": ["v0.9.0", "v0.9.1", "v0.9.2"],
    "ledger": ["2.0.0", "2.1.0-rc.1", "2.1.0-rc.2"],
}
POLICY = {"gateway": ">=1.4.0", "scheduler": "<v1.0.0"}


@pytest.fixture
def write_json(tmp_path: Path) -> Callable[[str, object], str]:
    """Write ``document`` as JSON to ``name`` in the temporary directory; return the path."""

    def write(name: str, document: object) -> str:
        path = tmp_path / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return str(path)

    return write


@pytest.fixture
def data_files(write_json: Callable[[str, object], str]) -> dict[str, str]:
    """Paths of a pin file, a release feed, and a policy file with the data above."""
    return {
        "pins": write_json("pins.json", {"components": PINS}),
        "releases": write_json("releases.json", RELEASES),
        "policy": write_json("policy.json", POLICY),
    }
