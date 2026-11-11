"""Rate limits per client, read from ``config/limits.toml``.

The file has a ``[default]`` limit, a table per client that has its own limit, and
optionally a list of other limit files to include::

    [policy]
    include = ["data/internal-limits.toml"]

    [default]
    burst = 20        # the most requests a client can send at once
    per_minute = 60   # the steady rate its bucket refills at

    [clients.reports-web]
    burst = 40
    per_minute = 120

Included paths are relative to the repository root (the parent of ``config/``). An
included file lists ``[clients.NAME]`` tables only. A client may be listed once across
all the files; a client that is not listed gets the ``[default]`` limit.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path("config/limits.toml")
LIMIT_KEYS = ("burst", "per_minute")
SECONDS_PER_MINUTE = 60


class PolicyError(ValueError):
    """A limits file that cannot be used."""


@dataclass(frozen=True)
class Limit:
    """A client's burst (bucket capacity) and steady rate (refill per minute)."""

    burst: int
    per_minute: int

    @property
    def per_second(self) -> float:
        """The refill rate in tokens per second."""
        return self.per_minute / SECONDS_PER_MINUTE


@dataclass(frozen=True)
class Policy:
    """The default limit and the clients that have their own."""

    default: Limit
    clients: Mapping[str, Limit]

    def limit_for(self, client: str) -> Limit:
        """The limit of ``client``: its own, or the default."""
        return self.clients.get(client, self.default)


def _limit(table: Any, where: str) -> Limit:
    if not isinstance(table, dict):
        raise PolicyError(f"{where}: expected a table with burst and per_minute")
    unknown = sorted(set(table) - set(LIMIT_KEYS))
    if unknown:
        raise PolicyError(f"{where}: unknown key {unknown[0]!r}")
    values = []
    for key in LIMIT_KEYS:
        value = table.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise PolicyError(f"{where}: {key} must be a whole number of at least 1")
        values.append(value)
    return Limit(*values)


def _read(path: Path, shown: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PolicyError(f"{shown}: file not found") from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"{shown}: not valid TOML ({exc})") from None


def _clients(data: dict[str, Any], shown: str, into: dict[str, tuple[Limit, str]]) -> None:
    clients = data.get("clients", {})
    if not isinstance(clients, dict):
        raise PolicyError(f"{shown}: [clients] must hold one table per client")
    for name, table in clients.items():
        if name in into:
            raise PolicyError(f"{shown}: client {name!r} is already listed in {into[name][1]}")
        into[name] = (_limit(table, f"{shown} [clients.{name}]"), shown)


def project_root(config: Path) -> Path:
    """The directory included paths are relative to: the parent of ``config/``."""
    return config.resolve().parent.parent


def load_policy(config: Path = DEFAULT_CONFIG) -> Policy:
    """Read the limits file ``config`` and the files it includes.

    Raises:
        PolicyError: A file is missing or invalid, or a client is listed twice.
    """
    data = _read(config, str(config))
    unknown = sorted(set(data) - {"policy", "default", "clients"})
    if unknown:
        raise PolicyError(f"{config}: unknown table or key {unknown[0]!r}")
    if "default" not in data:
        raise PolicyError(f"{config}: missing the [default] limit")
    default = _limit(data["default"], f"{config} [default]")
    found: dict[str, tuple[Limit, str]] = {}
    _clients(data, str(config), found)
    settings = data.get("policy", {})
    if not isinstance(settings, dict) or set(settings) - {"include"}:
        raise PolicyError(f"{config}: [policy] takes only an include list")
    include = settings.get("include", [])
    if not isinstance(include, list) or not all(isinstance(item, str) for item in include):
        raise PolicyError(f"{config}: [policy] include must be a list of paths")
    for rel in include:
        included = _read(project_root(config) / rel, rel)
        if set(included) - {"clients"}:
            raise PolicyError(f"{rel}: an included file lists [clients.NAME] tables only")
        if not included.get("clients"):
            raise PolicyError(f"{rel}: an included file must list at least one client")
        _clients(included, rel, found)
    return Policy(default, {name: limit for name, (limit, _) in sorted(found.items())})
