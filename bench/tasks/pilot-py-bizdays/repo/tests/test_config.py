from pathlib import Path

import pytest
from bizdays.config import ConfigError, calendar_source, project_root


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config" / "calendar.toml"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return path


def test_calendar_source_reads_the_value(tmp_path: Path) -> None:
    path = _config(tmp_path, '[calendar]\nsource = "data/closures.json"\n')
    assert calendar_source(path) == "data/closures.json"


def test_missing_configuration_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        calendar_source(tmp_path / "missing.toml")


def test_missing_source_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="source"):
        calendar_source(_config(tmp_path, "[calendar]\n"))


def test_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        calendar_source(_config(tmp_path, "[calendar\n"))


def test_project_root_is_the_parent_of_config(tmp_path: Path) -> None:
    assert project_root(_config(tmp_path, "")) == tmp_path.resolve()
