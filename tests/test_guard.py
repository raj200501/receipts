"""Tests for the billing guard."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from receipts import guard


def test_env_problems_reports_names_only() -> None:
    env = {
        "ANTHROPIC_BASE_URL": "https://example.invalid",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_USE_VERTEX": "",
        "PATH": "/usr/bin",
    }
    problems = guard.env_problems(env)
    assert [p.name for p in problems] == [
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
    ]
    assert all("example.invalid" not in p.describe() for p in problems)


def test_env_problems_presence_counts_even_when_empty() -> None:
    assert [p.name for p in guard.env_problems({"ANTHROPIC_API_KEY": ""})] == ["ANTHROPIC_API_KEY"]


def test_clean_env_has_no_problems() -> None:
    assert guard.env_problems({"HOME": "/root", "CLAUDE_CODE_ENTRYPOINT": "cli"}) == []


def test_settings_with_api_key_helper_is_a_problem(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"apiKeyHelper": "/bin/echo", "model": "x"}))
    problems = guard.settings_problems([settings, tmp_path / "missing.json"])
    assert problems == [guard.GuardProblem(str(settings), "apiKeyHelper")]
    assert "apiKeyHelper" in problems[0].describe()


def test_settings_without_helper_is_clean(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"permissions": {}}))
    assert guard.settings_problems([settings]) == []


def test_unreadable_settings_fail_closed(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{not json")
    assert [p.name for p in guard.settings_problems([settings])] == ["unreadable settings file"]


def test_default_settings_paths_include_project_files(tmp_path: Path) -> None:
    paths = guard.default_settings_paths(tmp_path / "home", tmp_path / "repo")
    assert tmp_path / "home" / ".claude" / "settings.json" in paths
    assert tmp_path / "repo" / ".claude" / "settings.local.json" in paths
    assert len(guard.default_settings_paths(tmp_path)) == len(paths) - 2


def test_billing_guard_combines_env_and_settings(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"apiKeyHelper": "x"}))
    problems = guard.billing_guard_problems(env={"ANTHROPIC_AUTH_TOKEN": "t"}, home=home)
    assert [p.name for p in problems] == ["ANTHROPIC_AUTH_TOKEN", "apiKeyHelper"]


def test_billing_guard_defaults_to_process_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    names = [p.name for p in guard.billing_guard_problems()]
    assert "ANTHROPIC_API_KEY" in names


def test_main_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in list(os.environ):
        if name in guard.GUARDED_ENV_VARS or name.startswith(guard.GUARDED_ENV_PREFIX):
            monkeypatch.delenv(name)
    assert guard.main() == 0
    assert "clear" in capsys.readouterr().out
    monkeypatch.setenv("CLAUDE_CODE_USE_FOUNDRY", "1")
    assert guard.main() == 1
    assert "DISABLED" in capsys.readouterr().out
