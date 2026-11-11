"""Tests for receipts.analysis._values (made-up values, no data)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from receipts.analysis._values import canonical, value_key


def test_arrays_compare_by_dtype_shape_and_elements() -> None:
    a = np.array([1.0, math.nan, -0.0])
    assert canonical(a) == canonical(np.array([1.0, float("nan"), 0.0]))
    assert hash(canonical(a)) == hash(canonical(np.array([1.0, float("nan"), 0.0])))
    assert canonical(a) != canonical(np.array([1.0, math.nan, 1e-300]))
    assert canonical(np.zeros(4)) != canonical(np.zeros((2, 2)))
    assert canonical(np.zeros(2)) != canonical(np.zeros(2, dtype=np.float32))
    assert canonical(np.arange(3)) == canonical(np.arange(3))
    small = np.array([-0.0, math.nan], dtype=np.float32)
    assert canonical(small) == canonical(np.array([0.0, math.nan], dtype=np.float32))


def test_mappings_tuples_and_scalars() -> None:
    assert canonical({"b": (1, 2), "a": 3}) == canonical({"a": 3, "b": (1, 2)})
    assert canonical({"a": 3}) != canonical({"a": 4})
    assert canonical((math.nan, "x")) == canonical((float("nan"), "x"))
    assert canonical(["w", math.nan]) == canonical(["w", float("nan")])
    assert canonical(["w"]) != canonical(("w",))  # as in Python, a list is not a tuple
    assert hash(canonical(["w", np.zeros(2)])) == hash(canonical(["w", np.zeros(2)]))
    assert canonical(2.5) == 2.5 and canonical("s") == "s"


def test_value_key_follows_the_fields() -> None:
    @dataclass(frozen=True, eq=False)
    class Holder:
        x: Any
        names: tuple[str, ...] = ()
        extra: dict[str, int] = field(default_factory=dict)

    first = Holder(np.array([1.0, 2.0]), ("a",), {"k": 1})
    assert value_key(first) == value_key(Holder(np.array([1.0, 2.0]), ("a",), {"k": 1}))
    assert value_key(first) != value_key(Holder(np.array([1.0, 2.0]), ("b",), {"k": 1}))
    assert len(value_key(first)) == 3
