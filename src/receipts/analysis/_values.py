"""Value equality and hashing for the frozen dataclasses that hold numpy arrays.

The generated ``__eq__`` of a dataclass compares fields with ``==``, which for numpy
arrays gives an array and makes ``a == b`` raise, and its ``__hash__`` fails on
arrays and dicts. :func:`value_key` maps an instance to a hashable tuple instead, so
``__eq__`` can compare keys and ``__hash__`` can hash them, which keeps the two
consistent.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Mapping
from dataclasses import fields
from typing import Any, cast

import numpy as np


def canonical(value: Any) -> Hashable:
    """A hashable stand-in for ``value``; two values get equal stand-ins when they are equal.

    Equal here means: arrays with the same dtype, shape, and elements, where NaN equals
    NaN and ``-0.0`` equals ``0.0`` (elements are compared as bytes after mapping both
    pairs to one form); mappings with equal items, in any order; tuples, or lists, that
    are equal element by element (a list never equals a tuple, as in Python); a float
    NaN and any other NaN. Any other value is returned unchanged and must be hashable.
    """
    if isinstance(value, np.ndarray):
        data = value
        if data.dtype.kind == "f":
            # One NaN bit pattern, and -0.0 + 0.0 is 0.0.
            data = np.where(np.isnan(data), np.nan, data + 0.0).astype(value.dtype)
        return ("ndarray", value.dtype.str, value.shape, data.tobytes())
    if isinstance(value, Mapping):
        return ("mapping", tuple((k, canonical(value[k])) for k in sorted(value, key=str)))
    if isinstance(value, tuple):
        return tuple(canonical(item) for item in value)
    if isinstance(value, list):
        return ("list", tuple(canonical(item) for item in value))
    if isinstance(value, float) and math.isnan(value):
        return ("nan",)
    return cast(Hashable, value)


def value_key(instance: Any) -> tuple[Hashable, ...]:
    """The :func:`canonical` form of every field of a dataclass instance, in field order."""
    return tuple(canonical(getattr(instance, f.name)) for f in fields(instance))
