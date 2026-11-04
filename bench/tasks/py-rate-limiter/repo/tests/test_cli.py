from pathlib import Path

import pytest
from throttle.cli import main

LIMITS = """
[default]
burst = 2
per_minute = 60

[clients.reports-web]
burst = 3
per_minute = 120
"""
LOG = """time,client,method,path
2026-10-28T14:00:00Z,reports-web,GET,/v1/reports
2026-10-28T14:00:00Z,reports-web,GET,/v1/reports
2026-10-28T14:00:00Z,mobile-app,GET,/v1/me
2026-10-28T14:00:00Z,mobile-app,GET,/v1/me
2026-10-28T14:00:00Z,mobile-app,GET,/v1/me
"""


def _files(tmp_path: Path, log: str = LOG) -> tuple[str, str]:
    config = tmp_path / "config" / "limits.toml"
    config.parent.mkdir()
    config.write_text(LIMITS, encoding="utf-8")
    requests = tmp_path / "requests.csv"
    requests.write_text(log, encoding="utf-8")
    return str(config), str(requests)


def test_limits_lists_the_default_and_the_clients(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = _files(tmp_path)
    assert main(["--config", config, "limits"]) == 0
    assert capsys.readouterr().out == (
        "client       burst  per_minute\n"
        "(default)        2          60\n"
        "reports-web      3         120\n"
    )


def test_replay_prints_the_totals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config, log = _files(tmp_path)
    assert main(["--config", config, "replay", log]) == 0
    assert capsys.readouterr().out == (
        "client       allowed  rejected\n"
        "mobile-app         2         1\n"
        "reports-web        2         0\n"
        "total              4         1\n"
    )


def test_replay_lists_rejected_requests(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config, log = _files(tmp_path)
    assert main(["--config", config, "replay", log, "--rejected"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "2026-10-28T14:00:00Z  mobile-app  GET /v1/me  retry after 1 s"
    )


def test_missing_configuration_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(tmp_path / "limits.toml"), "limits"]) == 2
    assert "file not found" in capsys.readouterr().err


def test_bad_log_row_exits_with_status_2_and_names_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, log = _files(tmp_path, LOG + "not a time,mobile-app,GET,/v1/me\n")
    assert main(["--config", config, "replay", log]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"throttle: {log}: line 7: invalid time 'not a time'\n"


def test_missing_log_exits_with_status_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = _files(tmp_path)
    assert main(["--config", config, "replay", str(tmp_path / "missing.csv")]) == 2
    assert "no such file" in capsys.readouterr().err
