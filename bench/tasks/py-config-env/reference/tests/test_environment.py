from pathlib import Path

import pytest
from thumbconf.cli import main
from thumbconf.loader import load_config, read_aliases, variable_name
from thumbconf.settings import BY_KEY
from thumbconf.values import ConfigError


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "thumbd.toml"
    path.write_text('[server]\nport = 9000\n\n[storage]\nbucket = "thumbs-file"\n')
    return path


def test_variable_names() -> None:
    assert variable_name(BY_KEY["server.port"]) == "THUMBD_SERVER_PORT"
    assert variable_name(BY_KEY["storage.timeout_s"]) == "THUMBD_STORAGE_TIMEOUT_S"


def test_variables_win_over_the_file_and_the_defaults(config_file: Path) -> None:
    environ = {"THUMBD_SERVER_PORT": "9443", "THUMBD_LOG_LEVEL": "warning"}
    config = load_config(config_file, environ=environ)
    assert config["server.port"] == 9443
    assert config["log.level"] == "warning"
    assert config["storage.bucket"] == "thumbs-file"


def test_os_environ_is_read_by_default(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THUMBD_STORAGE_BUCKET", "thumbs-env")
    assert load_config(config_file)["storage.bucket"] == "thumbs-env"
    assert load_config(config_file, environ={})["storage.bucket"] == "thumbs-file"


@pytest.mark.parametrize(
    ("name", "text", "key", "value"),
    [
        ("THUMBD_SERVER_DEBUG", "yes", "server.debug", True),
        ("THUMBD_SERVER_DEBUG", " Off ", "server.debug", False),
        ("THUMBD_SERVER_DEBUG", "1", "server.debug", True),
        ("THUMBD_SERVER_WORKERS", " 16 ", "server.workers", 16),
        ("THUMBD_STORAGE_TIMEOUT_S", "3", "storage.timeout_s", 3.0),
        ("THUMBD_STORAGE_TIMEOUT_S", "0.75", "storage.timeout_s", 0.75),
        ("THUMBD_THUMBS_SIZES", "64, 128,256", "thumbs.sizes", [64, 128, 256]),
        ("THUMBD_THUMBS_SIZES", "", "thumbs.sizes", []),
        ("THUMBD_THUMBS_FORMATS", "avif, webp", "thumbs.formats", ["avif", "webp"]),
    ],
)
def test_text_is_converted(
    config_file: Path, name: str, text: str, key: str, value: object
) -> None:
    got = load_config(config_file, environ={name: text})[key]
    assert got == value
    assert type(got) is type(value)


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("THUMBD_SERVER_PORT", "eighty", "THUMBD_SERVER_PORT: expected an integer, got 'eighty'"),
        ("THUMBD_SERVER_PORT", "70000", "THUMBD_SERVER_PORT: must be at most 65535"),
        ("THUMBD_SERVER_DEBUG", "maybe", "THUMBD_SERVER_DEBUG: expected true or false"),
        ("THUMBD_THUMBS_SIZES", "64,big", "THUMBD_THUMBS_SIZES item 2: expected an integer"),
        ("THUMBD_THUMBS_FORMATS", "webp,gif", r"THUMBD_THUMBS_FORMATS\[1\]: must be one of"),
    ],
)
def test_bad_variables_are_config_errors(
    config_file: Path, name: str, text: str, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(config_file, environ={name: text})


def test_cli_reports_a_bad_variable(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("THUMBD_SERVER_WORKERS", "many")
    assert main(["--config", str(config_file), "check"]) == 2
    assert capsys.readouterr().err == (
        "thumbconf: THUMBD_SERVER_WORKERS: expected an integer, got 'many'\n"
    )


@pytest.fixture
def aliased_file(tmp_path: Path) -> Path:
    (tmp_path / "env-aliases.toml").write_text(
        '[aliases]\nOLD_PORT = "server.port"\nOLD_BUCKET = "storage.bucket"\n'
    )
    path = tmp_path / "thumbd.toml"
    path.write_text("[server]\nport = 9000\n")
    return path


def test_alias_table_lists_known_settings(aliased_file: Path) -> None:
    aliases = read_aliases(aliased_file)
    assert aliases["server.port"] == ["OLD_PORT"]
    assert aliases["storage.bucket"] == ["OLD_BUCKET"]


def test_older_names_are_read_and_lose_to_thumbd_names(aliased_file: Path) -> None:
    environ = {"OLD_PORT": "9123", "OLD_BUCKET": "thumbs-prod-eu"}
    config = load_config(aliased_file, environ=environ)
    assert (config["server.port"], config["storage.bucket"]) == (9123, "thumbs-prod-eu")
    config = load_config(aliased_file, environ={**environ, "THUMBD_SERVER_PORT": "9200"})
    assert config["server.port"] == 9200


def test_bad_older_name_is_named(aliased_file: Path) -> None:
    with pytest.raises(ConfigError, match="OLD_PORT: expected an integer"):
        load_config(aliased_file, environ={"OLD_PORT": "eighty"})


def test_older_names_need_the_table_next_to_the_file(config_file: Path) -> None:
    config = load_config(config_file, environ={"OLD_PORT": "9123"})
    assert config["server.port"] == 9000


def test_alias_to_an_unknown_setting_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "env-aliases.toml").write_text('[aliases]\nOLD_PORT = "server.prot"\n')
    path = tmp_path / "thumbd.toml"
    path.write_text("")
    with pytest.raises(ConfigError, match=r"unknown setting 'server\.prot'"):
        load_config(path, environ={})
