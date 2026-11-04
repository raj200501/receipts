"""Read the bizdays configuration file (TOML)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path("config/calendar.toml")


class ConfigError(ValueError):
    """A configuration file that cannot be used."""


def _calendar_table(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML ({exc})") from None
    table = data.get("calendar", {})
    return table if isinstance(table, dict) else {}


def calendar_source(path: Path) -> str:
    """The ``[calendar] source`` value of the configuration file at ``path``."""
    source = _calendar_table(path).get("source")
    if not isinstance(source, str) or not source:
        raise ConfigError(f"{path}: [calendar] source must be a non-empty string")
    return source


def calendar_sources(path: Path) -> list[str]:
    """Every calendar source named by the configuration file at ``path``.

    ``[calendar] sources`` lists several sources; a file that still uses the single
    ``source`` key names one.
    """
    table = _calendar_table(path)
    if "sources" not in table:
        return [calendar_source(path)]
    if "source" in table:
        raise ConfigError(f"{path}: use either [calendar] source or sources, not both")
    sources = table["sources"]
    valid = isinstance(sources, list) and all(isinstance(s, str) and s for s in sources)
    if not valid or not sources:
        raise ConfigError(f"{path}: [calendar] sources must be a list of non-empty strings")
    return list(sources)


def project_root(path: Path) -> Path:
    """The directory calendar file paths are relative to: the parent of ``config/``."""
    return path.resolve().parent.parent
