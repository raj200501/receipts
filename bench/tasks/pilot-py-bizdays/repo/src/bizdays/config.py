"""Read the bizdays configuration file (TOML)."""

from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT_CONFIG = Path("config/calendar.toml")


class ConfigError(ValueError):
    """A configuration file that cannot be used."""


def calendar_source(path: Path) -> str:
    """The ``[calendar] source`` value of the configuration file at ``path``."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML ({exc})") from None
    source = data.get("calendar", {}).get("source")
    if not isinstance(source, str) or not source:
        raise ConfigError(f"{path}: [calendar] source must be a non-empty string")
    return source


def project_root(path: Path) -> Path:
    """The directory calendar file paths are relative to: the parent of ``config/``."""
    return path.resolve().parent.parent
