"""Tests for the sub-command environment of tools/ship_check.py (finding Z-build-3).

The harness runs every gate in a fresh clone so that only committed state counts.
Caller variables that change what runs there (an import path, pytest options, a
coverage config, make overrides, a different venv) must not leak into it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ship_check

LEAKING = {
    "PYTHONPATH": "/elsewhere/src",
    "PYTHONSTARTUP": "/elsewhere/startup.py",
    "PYTEST_ADDOPTS": "--deselect tests/test_broken.py::test_broken",
    "PYTEST_ARGS": "-k 'not verify'",
    "PY": "3.12",
    "COV_JSON": "/elsewhere/coverage.json",
    "COVERAGE_RCFILE": "/elsewhere/coveragerc",
    "COV_CORE_SOURCE": "receipts",
    "MAKEFLAGS": " -- RUN=true",
    "MFLAGS": "-i",
    "MAKEFILES": "/elsewhere/extra.mk",
    "MAKELEVEL": "3",
    "MYPYPATH": "/elsewhere/stubs",
    "BASH_ENV": "/elsewhere/bashrc",
    "ENV": "/elsewhere/shrc",
    "BASH_FUNC_uv%%": "() { true; }",
    "UV_PROJECT_ENVIRONMENT": "/elsewhere/.venv",
    "UV_PROJECT": "/elsewhere",
    "UV_WORKING_DIR": "/elsewhere",
    "UV_ENV_FILE": "/elsewhere/.env",
    "UV_NO_PROJECT": "1",
    "UV_PYTHON": "3.12",
    "VIRTUAL_ENV": "/elsewhere/.venv",
    "CONDA_PREFIX": "/elsewhere/conda",
}
KEPT = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/root",
    "HTTPS_PROXY": "http://proxy.invalid:3128",
    "SSL_CERT_FILE": "/etc/ssl/cert.pem",
    "UV_CACHE_DIR": "/cache/uv",
    "UV_OFFLINE": "1",
    "CAP_SHARE": "0.2",
    # secrets_scan.py compares tracked files with the values of secret-named variables.
    "SYNTH_SERVICE_TOKEN": "synthetic-token-value-for-the-scan",
}


def make_context(tmp_path: Path) -> ship_check.Context:
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=tmp_path, clone=tmp_path, logs=logs, fast=False, sha="0" * 40)


def test_env_drops_variables_that_change_what_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in {**LEAKING, **KEPT}.items():
        monkeypatch.setenv(key, value)
    env = make_context(tmp_path).env({"RECEIPTS_OFFLINE": "1"})
    leaked = sorted(key for key in LEAKING if key in env)
    assert leaked == []
    assert {key: env.get(key) for key in KEPT} == KEPT
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["RECEIPTS_OFFLINE"] == "1"


def test_scrub_reports_dropped_names_only() -> None:
    kept, dropped = ship_check.scrub_environment({**LEAKING, **KEPT})
    assert dropped == sorted(LEAKING)
    assert kept == KEPT


def test_make_pins_knobs_on_the_command_line(tmp_path: Path) -> None:
    # Synthetic Makefile: prints the knobs make resolved, so the pins are visible.
    (tmp_path / "Makefile").write_text(
        "PY ?= 3.11\nPYTEST_ARGS ?=\nshow:\n\t@echo 'PY=$(PY) ARGS=[$(PYTEST_ARGS)]'\n"
    )
    ctx = make_context(tmp_path)
    result = ctx.make("show", 60)
    assert result.ok and result.stdout.strip() == "PY=3.11 ARGS=[]"
    later = ctx.run(
        "show-fast",
        ["make", "--no-print-directory", "show", *ship_check.MAKE_PINS, "PYTEST_ARGS=-k x"],
        60,
    )
    assert later.stdout.strip() == "PY=3.11 ARGS=[-k x]"


def test_make_pins_beat_environment_and_makeflags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Makefile").write_text(
        "PY ?= 3.11\nPYTEST_ARGS ?=\nRUN := uv run\n"
        "show:\n\t@echo 'PY=$(PY) ARGS=[$(PYTEST_ARGS)] RUN=[$(RUN)]'\n"
    )
    monkeypatch.setenv("PY", "3.12")
    monkeypatch.setenv("PYTEST_ARGS", "-k nothing")
    monkeypatch.setenv("MAKEFLAGS", " -- RUN=true")
    result = make_context(tmp_path).make("show", 60)
    assert result.stdout.strip() == "PY=3.11 ARGS=[] RUN=[uv run]"
