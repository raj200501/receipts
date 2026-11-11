"""Load the configuration: every default, overridden by the values of a TOML file and
then by environment variables.

A setting ``section.key`` is set by the variable ``THUMBD_SECTION_KEY`` (upper case,
see :func:`variable_name`). The deployment templates of the shared platform still set
some settings under older names; the platform team lists them in an alias table,
``env-aliases.toml``, which is used for a configuration file that has one next to it.
When a THUMBD_ variable and an older name are both set, the THUMBD_ variable wins.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from thumbconf.config import Config
from thumbconf.settings import BY_KEY, SETTINGS, Setting
from thumbconf.values import ConfigError, check_value, convert_text

DEFAULT_PATH = Path("config/thumbd.toml")
ENV_PREFIX = "THUMBD_"
ALIASES_FILE = "env-aliases.toml"


def variable_name(setting: Setting) -> str:
    """The environment variable that sets ``setting``: ``THUMBD_SERVER_PORT`` for server.port."""
    return f"{ENV_PREFIX}{setting.section.upper()}_{setting.name.upper()}"


def _read_toml(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML ({exc})") from None


def read_file(path: Path) -> dict[str, object]:
    """The checked values of a TOML configuration file, by ``section.key``.

    Every table must be a section of :data:`SETTINGS` and every key one of its
    settings; a value of the wrong kind or out of its limits is an error.

    Raises:
        ConfigError: the file is missing, is not valid TOML, or has a bad setting.
    """
    data = _read_toml(path)
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


def read_aliases(config_path: Path) -> dict[str, list[str]]:
    """The older variable names for each setting, from the alias table next to ``config_path``.

    The table (``env-aliases.toml``) maps variable names to settings under
    ``[aliases]``. Without a table there are no older names.

    Raises:
        ConfigError: the table is not valid TOML or names an unknown setting.
    """
    path = config_path.parent / ALIASES_FILE
    if not path.is_file():
        return {}
    table = _read_toml(path).get("aliases", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: aliases must be a table ([aliases])")
    names: dict[str, list[str]] = {}
    for variable, key in table.items():
        if not isinstance(key, str) or key not in BY_KEY:
            raise ConfigError(f"{path}: {variable} names an unknown setting {key!r}")
        names.setdefault(key, []).append(variable)
    return names


def read_environment(
    environ: Mapping[str, str], aliases: Mapping[str, list[str]] | None = None
) -> dict[str, object]:
    """The converted values of the variables set in ``environ``, by ``section.key``.

    The THUMBD_ variable of a setting is used when it is set; otherwise the first of its
    older names (from ``aliases``) that is set.

    Raises:
        ConfigError: a variable cannot be converted or fails the setting's checks; the
            message names the variable.
    """
    values: dict[str, object] = {}
    for setting in SETTINGS:
        names = [variable_name(setting), *(aliases or {}).get(setting.key, [])]
        for name in names:
            if name in environ:
                values[setting.key] = convert_text(setting, environ[name], name)
                break
    return values


def defaults() -> dict[str, object]:
    """The default of every setting (lists as new lists)."""
    return {
        setting.key: list(setting.default)
        if isinstance(setting.default, tuple)
        else setting.default
        for setting in SETTINGS
    }


def load_config(path: Path | str | None = None, environ: Mapping[str, str] | None = None) -> Config:
    """Every setting: its default, overridden by the file at ``path``, then by variables.

    Variables come from ``environ`` when it is given (tests pass their own mapping) and
    from ``os.environ`` otherwise. Without ``path`` there is no file and no alias table.

    Raises:
        ConfigError: the file, the alias table, or a variable cannot be used.
    """
    values = defaults()
    aliases: dict[str, list[str]] = {}
    if path is not None:
        values.update(read_file(Path(path)))
        aliases = read_aliases(Path(path))
    values.update(read_environment(os.environ if environ is None else environ, aliases))
    return Config(values)
