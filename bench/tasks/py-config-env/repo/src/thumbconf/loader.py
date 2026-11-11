"""Load the configuration: every default, overridden by the values of a TOML file."""

from __future__ import annotations

import tomllib
from pathlib import Path

from thumbconf.config import Config
from thumbconf.settings import BY_KEY, SETTINGS
from thumbconf.values import ConfigError, check_value

DEFAULT_PATH = Path("config/thumbd.toml")


def read_file(path: Path) -> dict[str, object]:
    """The checked values of a TOML configuration file, by ``section.key``.

    Every table must be a section of :data:`SETTINGS` and every key one of its
    settings; a value of the wrong kind or out of its limits is an error.

    Raises:
        ConfigError: the file is missing, is not valid TOML, or has a bad setting.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML ({exc})") from None
    values: dict[str, object] = {}
    for section, table in data.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: {section} must be a table ([{section}])")
        for name, value in table.items():
            key = f"{section}.{name}"
            setting = BY_KEY.get(key)
            if setting is None:
                raise ConfigError(f"{path}: unknown setting {key}")
            values[key] = check_value(setting, value, f"{path}: {key}")
    return values


def defaults() -> dict[str, object]:
    """The default of every setting (lists as new lists)."""
    return {
        setting.key: list(setting.default)
        if isinstance(setting.default, tuple)
        else setting.default
        for setting in SETTINGS
    }


def load_config(path: Path | str | None = None) -> Config:
    """Every setting: its default, overridden by the configuration file at ``path``.

    Without ``path`` the configuration is the defaults only.

    Raises:
        ConfigError: the file cannot be used (see :func:`read_file`).
    """
    values = defaults()
    if path is not None:
        values.update(read_file(Path(path)))
    return Config(values)
