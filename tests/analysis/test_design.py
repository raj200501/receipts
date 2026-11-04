"""Tests for receipts.analysis.design (all records are synthetic, written by hand)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from receipts.analysis.design import (
    INTERCEPT,
    Design,
    Formula,
    build_design,
    interaction_column,
    treatment_column,
)

# Synthetic records: manipulation levels and outcomes are made up for the test.
RECORDS: list[dict[str, Any]] = [
    {"task": "t2", "M1": "unattainable", "M4": "short", "y": 1},
    {"task": "t1", "M1": "attainable", "M4": "long", "y": 0},
    {"task": "t1", "M1": "unattainable", "M4": "long", "y": True},
    {"task": "t2", "M1": "attainable", "M4": "short", "y": 0.0},
    {"task": "t3", "M1": "attainable", "M4": "long", "y": False},
]


def test_column_name_helpers() -> None:
    assert treatment_column("M1", "unattainable") == "M1[T.unattainable]"
    assert interaction_column("M1", "u", "M2", "t") == "M1[T.u]:M2[T.t]"
    assert INTERCEPT == "(Intercept)"


def test_treatment_coding_with_default_and_explicit_reference() -> None:
    formula = Formula(response="y", factors=["M1", "M4"], reference={"M4": "short"}, group="task")
    design = build_design(RECORDS, formula)
    assert design.column_names == (INTERCEPT, "M1[T.unattainable]", "M4[T.long]")
    assert design.levels == {"M1": ("attainable", "unattainable"), "M4": ("short", "long")}
    expected = np.array([[1, 1, 0], [1, 0, 1], [1, 1, 1], [1, 0, 0], [1, 0, 1]], dtype=float)
    assert np.array_equal(design.x, expected)
    assert np.array_equal(design.y, [1.0, 0.0, 1.0, 0.0, 0.0])
    assert design.group_labels == ("t1", "t2", "t3")
    assert design.groups is not None
    assert design.groups.tolist() == [1, 0, 0, 1, 2]
    assert (design.n_obs, design.n_params, design.n_groups) == (5, 3, 3)


def test_interaction_columns_are_products() -> None:
    records = [
        {"A": a, "B": b, "y": (i + j) % 2}
        for i, a in enumerate(("a0", "a1"))
        for j, b in enumerate(("b0", "b1", "b2"))
        for _ in range(2)
    ]
    design = build_design(records, Formula("y", ("A", "B"), interactions=(("A", "B"),)))
    assert design.column_names == (
        INTERCEPT,
        "A[T.a1]",
        "B[T.b1]",
        "B[T.b2]",
        "A[T.a1]:B[T.b1]",
        "A[T.a1]:B[T.b2]",
    )
    x = design.x
    assert np.array_equal(x[:, 4], x[:, 1] * x[:, 2])
    assert np.array_equal(x[:, 5], x[:, 1] * x[:, 3])
    assert design.groups is None and design.n_groups == 0


def test_numpy_response_values_are_accepted() -> None:
    # Synthetic records whose outcomes came out of numpy (bool_, int64, float64).
    records = [
        {"A": "a0", "y": np.True_},
        {"A": "a1", "y": np.False_},
        {"A": "a0", "y": np.int64(1)},
        {"A": "a1", "y": np.float64(0.0)},
    ]
    design = build_design(records, Formula("y", ("A",)))
    assert design.y.tolist() == [1.0, 0.0, 1.0, 0.0]
    with pytest.raises(ValueError, match="must be 0 or 1"):
        build_design([{"A": "a0", "y": np.int64(2)}], Formula("y"))


def test_intercept_only_design_and_non_string_levels() -> None:
    design = build_design([{"y": 1, "k": 2}, {"y": 0, "k": 10}], Formula("y"))
    assert design.column_names == (INTERCEPT,)
    numeric = build_design(
        [{"y": 1, "k": 2}, {"y": 0, "k": 10}, {"y": 1, "k": 2}], Formula("y", ("k",))
    )
    assert numeric.levels["k"] == ("10", "2")  # labels are strings, sorted as strings
    assert numeric.column_names == (INTERCEPT, "k[T.2]")


@pytest.mark.parametrize(
    ("records", "formula", "message"),
    [
        ([{"y": 1}], Formula("y", ("M1",)), "record 0 has no field 'M1'"),
        ([{"y": 1, "M1": None}], Formula("y", ("M1",)), "record 0 has no value for 'M1'"),
        ([{"M1": "a"}], Formula("y", ("M1",)), "record 0 has no field 'y'"),
        ([{"y": 2, "M1": "a"}], Formula("y", ("M1",)), "must be 0 or 1"),
        ([{"y": "yes", "M1": "a"}], Formula("y", ("M1",)), "must be 0 or 1"),
        ([{"y": 1, "M1": "a"}, {"y": 0, "M1": "a"}], Formula("y", ("M1",)), "single observed"),
        (
            [{"y": 1, "M1": "a"}, {"y": 0, "M1": "b"}],
            Formula("y", ("M1",), reference={"M1": "c"}),
            "reference level 'c'",
        ),
        (
            [{"y": 1, "M1": "a"}, {"y": 0, "M1": "b"}],
            Formula("y", ("M1",), group="task"),
            "record 0 has no field 'task'",
        ),
        ([], Formula("y"), "no records"),
    ],
)
def test_build_design_rejects_bad_records(
    records: list[dict[str, Any]], formula: Formula, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_design(records, formula)


def test_build_design_reports_rank_deficient_interactions() -> None:
    # The cell (a1, b1) never occurs, so the interaction column is all zeros.
    records = [
        {"A": "a0", "B": "b0", "y": 0},
        {"A": "a1", "B": "b0", "y": 1},
        {"A": "a0", "B": "b1", "y": 1},
        {"A": "a0", "B": "b0", "y": 1},
    ]
    with pytest.raises(ValueError, match=r"rank deficient.*A\[T\.a1\]:B\[T\.b1\]"):
        build_design(records, Formula("y", ("A", "B"), interactions=(("A", "B"),)))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"response": ""}, "response"),
        ({"response": "y", "factors": ("y",)}, "response"),
        ({"response": "y", "factors": ("A", "A")}, "more than once"),
        ({"response": "y", "factors": ("A",), "interactions": (("A", "B"),)}, "not a factor"),
        ({"response": "y", "factors": ("A",), "interactions": (("A", "A"),)}, "two different"),
        (
            {"response": "y", "factors": ("A", "B"), "interactions": (("A", "B"), ("B", "A"))},
            "more than once",
        ),
        ({"response": "y", "factors": ("A",), "reference": {"B": "x"}}, "not a factor"),
        ({"response": "y", "factors": ("A",), "group": "A"}, "group"),
        ({"response": "y", "group": "y"}, "group"),
    ],
)
def test_formula_validation(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Formula(**kwargs)


def test_formula_normalises_sequences() -> None:
    formula = Formula("y", ["A", "B"], interactions=[("A", "B")], reference={"A": "a"})
    assert formula.factors == ("A", "B")
    assert formula.interactions == (("A", "B"),)
    assert dict(formula.reference) == {"A": "a"}


def _x(*rows: list[float]) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.array(rows, dtype=np.float64)


def test_design_from_arrays_and_validation() -> None:
    design = Design(
        x=_x([1, 0], [1, 1], [1, 0]), y=np.array([0.0, 1.0, 1.0]), column_names=("a", "b")
    )
    assert design.n_obs == 3 and design.n_params == 2
    with pytest.raises(ValueError):
        design.x[0, 0] = 5.0  # arrays are read-only
    grouped = Design(
        x=_x([1, 0], [1, 1], [1, 0]),
        y=np.array([0.0, 1.0, 1.0]),
        column_names=("a", "b"),
        groups=np.array([1, 0, 1]),
    )
    assert grouped.group_labels == ("0", "1")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"x": np.ones(3)}, "two-dimensional"),
        ({"x": np.ones((0, 1)), "y": np.ones(0)}, "at least one"),
        ({"y": np.array([0.0, 1.0])}, "length"),
        ({"y": np.array([0.0, 0.5, 1.0])}, "0 or 1"),
        ({"x": _x([1, np.nan], [1, 1], [1, 0])}, "finite"),
        ({"column_names": ("a",)}, "column names"),
        ({"column_names": ("a", "a")}, "unique"),
        ({"groups": np.array([0, 2, 2])}, "every cluster"),
        ({"groups": np.array([0, 1])}, "length"),
        ({"groups": np.array([0, -1, 1])}, "every cluster"),
        ({"groups": np.array([0.0, 1.0, 1.0])}, "integers"),
        ({"groups": np.array([0, 1, 1]), "group_labels": ("only",)}, "labels"),
        ({"x": _x([1, 2], [1, 2], [1, 2])}, r"rank deficient.*\bb\b"),
    ],
)
def test_design_rejects_bad_arrays(kwargs: dict[str, Any], message: str) -> None:
    base: dict[str, Any] = {
        "x": _x([1, 0], [1, 1], [1, 0]),
        "y": np.array([0.0, 1.0, 1.0]),
        "column_names": ("a", "b"),
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        Design(**base)


def test_design_with_response_keeps_everything_else() -> None:
    design = build_design(RECORDS, Formula("y", ("M1",), group="task"))
    regrouped = design.with_response(np.array([1.0, 1.0, 0.0, 0.0, 1.0]))
    assert regrouped.groups is not None and design.groups is not None
    assert np.array_equal(regrouped.groups, design.groups)
    assert np.array_equal(regrouped.y, [1.0, 1.0, 0.0, 0.0, 1.0])
    assert regrouped.column_names == design.column_names
