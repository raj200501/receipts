"""Cache keys for function calls."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from typing import Any

_KWARGS_MARK = ("<kwargs>",)


def make_key(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> Hashable:
    """A hashable key for a call; keyword order does not matter.

    Raises TypeError, naming the argument, when an argument is not hashable.
    """
    for index, value in enumerate(args):
        _require_hashable(value, f"argument {index}")
    for name, value in kwargs.items():
        _require_hashable(value, f"argument {name!r}")
    if not kwargs:
        return args
    return (*args, _KWARGS_MARK, *sorted(kwargs.items()))


def _require_hashable(value: Any, label: str) -> None:
    try:
        hash(value)
    except TypeError:
        raise TypeError(f"cannot cache a call whose {label} is unhashable: {value!r}") from None
