from pathlib import Path

import pytest
from thumbconf.loader import load_config
from thumbconf.values import ConfigError

REPOSITORY = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "thumbd.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_without_a_file_every_setting_has_its_default() -> None:
    config = load_config()
    assert len(config) == 12
    assert config["server.port"] == 8080
    assert config["thumbs.formats"] == ["webp", "jpeg"]


def test_file_values_override_the_defaults(tmp_path: Path) -> None:
    path = _config(tmp_path, '[server]\nport = 9000\n\n[log]\nlevel = "warning"\n')
    config = load_config(path)
    assert config["server.port"] == 9000
    assert config["log.level"] == "warning"
    assert config["server.workers"] == 4


def test_the_development_configuration_loads() -> None:
    config = load_config(REPOSITORY / "config" / "thumbd.toml")
    assert config["server.host"] == "0.0.0.0"
    assert config["thumbs.sizes"] == [128, 256, 512, 1024]


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="configuration file not found"):
        load_config(tmp_path / "missing.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(_config(tmp_path, "[server\nport = 1\n"))


def test_unknown_setting(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"unknown setting server\.prot"):
        load_config(_config(tmp_path, "[server]\nprot = 9000\n"))


def test_a_section_must_be_a_table(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"server must be a table"):
        load_config(_config(tmp_path, "server = 1\n"))


def test_file_errors_name_the_file_and_the_setting(tmp_path: Path) -> None:
    path = _config(tmp_path, "[thumbs]\nquality = 0\n")
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert str(info.value) == f"{path}: thumbs.quality: must be at least 1, got 0"
