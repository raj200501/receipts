"""Turn command-line text into stored values, and stored values back into text."""

from __future__ import annotations

import json
from typing import Any


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not stored as a number")


def parse_value(text: str, *, as_string: bool = False) -> Any:
    """The value ``kvstore set KEY TEXT`` stores.

    Text that is a JSON value (a number, ``true``, ``false``, ``null``, a quoted string, a
    list, or an object) is stored as that value; any other text, and every text when
    ``as_string`` is set, is stored as the string itself. ``NaN`` and ``Infinity`` are
    stored as strings, because they are not JSON.
    """
    if as_string:
        return text
    try:
        return json.loads(text, parse_constant=_no_constants)
    except ValueError:
        return text


def format_value(value: Any) -> str:
    """How ``kvstore get`` and ``kvstore list`` print a value.

    Strings are printed as they are; every other value is printed as compact JSON.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)
