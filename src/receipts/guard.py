"""Billing guard for Claude children (docs/BUILD_BRIEF.md section 8).

Claude Code bills per token when an API key, an auth token, a custom base URL,
an alternative provider (any ``CLAUDE_CODE_USE_*`` variable), or an
``apiKeyHelper`` setting is configured, even when a Max plan login exists.
Every code path that would launch a Claude child calls
:func:`billing_guard_problems` first and refuses to launch while it returns
anything. Only names are ever reported, never values.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

GUARDED_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
)
GUARDED_ENV_PREFIX = "CLAUDE_CODE_USE_"
API_KEY_HELPER_SETTING = "apiKeyHelper"


@dataclass(frozen=True)
class GuardProblem:
    """One reason the billing guard refuses to launch Claude children.

    Attributes:
        source: ``"env"`` for an environment variable, otherwise the settings file path.
        name: The variable or setting name. Never its value.
    """

    source: str
    name: str

    def describe(self) -> str:
        """Return a one-line, value-free description for STATUS.md and logs."""
        if self.source == "env":
            return f"environment variable {self.name} is set"
        return f"setting {self.name} is present in {self.source}"


def env_problems(env: Mapping[str, str]) -> list[GuardProblem]:
    """Return a problem for every guarded variable present in ``env``.

    Presence is enough: an empty ``ANTHROPIC_BASE_URL`` still changes how the
    CLI authenticates on some versions, so the guard does not inspect values.
    """
    names = [name for name in GUARDED_ENV_VARS if name in env]
    names.extend(sorted(name for name in env if name.startswith(GUARDED_ENV_PREFIX)))
    return [GuardProblem("env", name) for name in names]


def default_settings_paths(home: Path, repo: Path | None = None) -> list[Path]:
    """Return the Claude Code settings files that could carry ``apiKeyHelper``.

    Covers user settings, project settings when ``repo`` is given, and the
    managed-settings locations on Linux and macOS.
    """
    paths = [
        home / ".claude" / "settings.json",
        home / ".claude" / "settings.local.json",
        Path("/etc/claude-code/managed-settings.json"),
        Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    ]
    if repo is not None:
        paths.extend([repo / ".claude" / "settings.json", repo / ".claude" / "settings.local.json"])
    return paths


def settings_problems(paths: Iterable[Path]) -> list[GuardProblem]:
    """Return a problem for every settings file that defines ``apiKeyHelper``.

    A settings file that exists but cannot be parsed is also a problem: the
    guard cannot prove it is safe, so it fails closed.
    """
    problems: list[GuardProblem] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            problems.append(GuardProblem(str(path), "unreadable settings file"))
            continue
        if isinstance(data, dict) and API_KEY_HELPER_SETTING in data:
            problems.append(GuardProblem(str(path), API_KEY_HELPER_SETTING))
    return problems


def billing_guard_problems(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    repo: Path | None = None,
) -> list[GuardProblem]:
    """Return every reason a Claude child must not be launched (empty means clear).

    Args:
        env: Environment to inspect; defaults to ``os.environ``.
        home: Home directory for user settings; defaults to ``Path.home()``.
        repo: Repository root for project settings; skipped when ``None``.
    """
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    return env_problems(env) + settings_problems(default_settings_paths(home, repo))


def main(argv: list[str] | None = None) -> int:
    """Print guard problems by name and exit 1 if any exist."""
    del argv
    problems = billing_guard_problems(repo=Path.cwd())
    for problem in problems:
        print(f"billing guard: {problem.describe()}")
    if problems:
        print("billing guard: Claude children are DISABLED")
        return 1
    print("billing guard: clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
