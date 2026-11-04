"""Fixtures for the sandbox tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from .helpers import PLANTED_SECRETS


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """An empty workspace directory with one subdirectory, ``sub``."""
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    return root


@pytest.fixture
def planted_secrets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Put synthetic credential variables into this process's environment."""
    for name, value in PLANTED_SECRETS.items():
        monkeypatch.setenv(name, value)
    return dict(PLANTED_SECRETS)
