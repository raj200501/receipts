from pathlib import Path

import pytest
from thumbconf.cli import main


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "thumbd.toml"
    path.write_text(
        '[server]\nhost = "0.0.0.0"\nport = 9000\n\n[thumbs]\nformats = ["avif"]\n',
        encoding="utf-8",
    )
    return path


def test_show_prints_every_setting(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(config_file), "show"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        'server.host = "0.0.0.0"',
        "server.port = 9000",
        "server.workers = 4",
        "server.debug = false",
        'storage.bucket = "thumbs-dev"',
        'storage.endpoint = "http://localhost:9000"',
        "storage.timeout_s = 5.0",
        "thumbs.sizes = [128, 256, 512]",
        'thumbs.formats = ["avif"]',
        "thumbs.quality = 82",
        'log.level = "info"',
        "log.json = false",
    ]


def test_get_prints_one_value(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(config_file), "get", "thumbs.formats"]) == 0
    assert capsys.readouterr().out == '["avif"]\n'


def test_get_of_an_unknown_setting_exits_with_status_2(
    config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(config_file), "get", "server.prot"]) == 2
    assert capsys.readouterr().err == "thumbconf: unknown setting server.prot\n"


def test_check_says_ok(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(config_file), "check"]) == 0
    assert capsys.readouterr().out == f"{config_file}: ok\n"


def test_unusable_configuration_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "thumbd.toml"
    path.write_text("[server]\nport = 80800\n", encoding="utf-8")
    assert main(["--config", str(path), "check"]) == 2
    assert capsys.readouterr().err == (
        f"thumbconf: {path}: server.port: must be at most 65535, got 80800\n"
    )


def test_missing_configuration_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(tmp_path / "missing.toml"), "show"]) == 2
    assert "configuration file not found" in capsys.readouterr().err
