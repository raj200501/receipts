"""The effective configuration: one checked value for every setting."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from thumbconf.settings import SETTINGS


class Config(Mapping[str, object]):
    """Read-only values by ``section.key``, in the order of :data:`SETTINGS`.

    ``config["server.port"]`` is one value; ``config.section("server")`` is the values
    of one table by their key (``{"host": ..., "port": ...}``).
    """

    def __init__(self, values: Mapping[str, object]) -> None:
        order = [setting.key for setting in SETTINGS]
        self._values = {key: values[key] for key in order if key in values}

    def __getitem__(self, key: str) -> object:
        try:
            return self._values[key]
        except KeyError:
            raise KeyError(f"unknown setting {key!r}") from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def section(self, name: str) -> dict[str, object]:
        """The values of one table, by their key inside the table."""
        prefix = f"{name}."
        return {
            key.removeprefix(prefix): value
            for key, value in self._values.items()
            if key.startswith(prefix)
        }

    def __repr__(self) -> str:
        return f"Config({self._values!r})"
