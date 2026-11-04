"""Design matrices for binary-outcome models: treatment-coded factors and two-way interactions.

A :class:`Formula` is a small stand-in for a model formula such as
``y ~ M1 + M2 + M1:M2 + (1 | task_id)``. It names the response field, the
categorical factors, two-way interactions between factors, reference levels, and
the field whose values define clusters for a random intercept.
:func:`build_design` turns records (mappings whose top-level fields the formula
names) into a :class:`Design`; a :class:`Design` can also be built directly from
arrays.

Rows of ``artifacts/e1/runs.jsonl`` (written by ``receipts.study.aggregate.e1_rows``)
keep the arm (``config_id``), task (``task_id``), and outcomes (``false_success``,
``any_contradicted``) at the top level, but the manipulation levels inside a nested
mapping, ``{"conditions": {"M1": "attainable", ...}}``. :func:`flatten_records`
copies them to the top level. The design of the preregistered E1 model
(``prereg/0001-e1-main-study.md``, section 7) is then, for the included rows,
``build_design(flatten_records(rows), Formula("false_success", ("config_id", "M1",
..., "M5"), reference={"config_id": "ma-qwen7b", ...}, group="task_id"))``;
``tests/analysis/test_workflow.py`` runs this on synthetic rows built by ``e1_rows``.

Coding rules:

- Every factor value is converted to a string label with ``str``; ``None`` or a
  missing field is an error, never a level.
- A factor's levels are its observed labels, sorted as strings. The reference level
  is the one named in ``Formula.reference``, otherwise the first sorted level, and
  it is listed first in ``Design.levels``.
- Columns are ``(Intercept)``; then, factor by factor, one 0/1 indicator per
  non-reference level, named ``factor[T.level]``; then, interaction by interaction,
  the products of the two factors' indicators, named ``a[T.la]:b[T.lb]``, with the
  levels of ``a`` varying slowest.
- Clusters are numbered in sorted order of their string labels.

A design must have full column rank: a design whose columns are linearly dependent
(for example an interaction whose cell never occurs) is rejected with the names of
the dependent columns, because its coefficients are not identifiable.
"""

from __future__ import annotations

import numbers
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from receipts.analysis._values import value_key

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.intp]

INTERCEPT = "(Intercept)"


def treatment_column(factor: str, level: str) -> str:
    """Name of the indicator column for ``level`` of ``factor``, e.g. ``M1[T.unattainable]``."""
    return f"{factor}[T.{level}]"


def interaction_column(factor_a: str, level_a: str, factor_b: str, level_b: str) -> str:
    """Name of the product of two indicator columns, e.g. ``M1[T.u]:M2[T.t]``."""
    return f"{treatment_column(factor_a, level_a)}:{treatment_column(factor_b, level_b)}"


@dataclass(frozen=True)
class Formula:
    """Response, factors, interactions, reference levels, and the cluster field.

    Formulas compare by value and are hashable (the hash leaves out ``reference``,
    which is a dict).

    Attributes:
        response: Field holding the binary outcome (a Python or numpy bool, or a number
            equal to 0 or 1).
        factors: Fields treated as categorical factors, in column order.
        interactions: Pairs of factors whose two-way interaction is included.
        reference: Reference level per factor (as a string label); others default to
            the first sorted level.
        group: Field holding the cluster ID (the task), or None for no clusters.
    """

    response: str
    factors: Sequence[str] = ()
    interactions: Sequence[tuple[str, str]] = ()
    reference: Mapping[str, str] = field(default_factory=dict, hash=False)
    group: str | None = None

    def __post_init__(self) -> None:
        factors = tuple(self.factors)
        interactions = tuple((str(a), str(b)) for a, b in self.interactions)
        reference = {str(k): str(v) for k, v in self.reference.items()}
        object.__setattr__(self, "factors", factors)
        object.__setattr__(self, "interactions", interactions)
        object.__setattr__(self, "reference", reference)
        if not self.response:
            raise ValueError("the response field name must be non-empty")
        if self.response in factors:
            raise ValueError(f"the response {self.response!r} cannot also be a factor")
        if len(set(factors)) != len(factors):
            raise ValueError("a factor is listed more than once")
        if self.group is not None and (self.group in factors or self.group == self.response):
            raise ValueError(f"the group field {self.group!r} cannot be a factor or the response")
        seen: set[frozenset[str]] = set()
        for a, b in interactions:
            if a == b:
                raise ValueError(f"an interaction needs two different factors, got {a!r} twice")
            for name in (a, b):
                if name not in factors:
                    raise ValueError(f"interaction term {name!r} is not a factor")
            pair = frozenset((a, b))
            if pair in seen:
                raise ValueError(f"the interaction {a}:{b} is listed more than once")
            seen.add(pair)
        for name in reference:
            if name not in factors:
                raise ValueError(f"reference level given for {name!r}, which is not a factor")


def _dependent_columns(x: FloatArray, names: Sequence[str]) -> list[str]:
    """Columns that are linear combinations of earlier columns."""
    kept: list[int] = []
    dependent: list[str] = []
    for j in range(x.shape[1]):
        if np.linalg.matrix_rank(x[:, [*kept, j]]) > len(kept):
            kept.append(j)
        else:
            dependent.append(names[j])
    return dependent


@dataclass(frozen=True, eq=False)
class Design:
    """A full-rank design matrix, a binary response, and optional cluster labels.

    Arrays are copied and made read-only on construction. Designs compare and hash by
    value: two are equal when every field is (arrays element by element).

    Attributes:
        x: Design matrix, shape ``(n_obs, n_params)``, finite floats.
        y: Response, shape ``(n_obs,)``, every value 0.0 or 1.0.
        column_names: One unique name per column of ``x``.
        groups: Cluster index of each observation (``0 .. n_groups - 1``, every index
            used), or None.
        group_labels: Label of each cluster index; defaults to the indices as strings.
        levels: Levels of each factor, reference first (empty for array-built designs).
    """

    x: FloatArray
    y: FloatArray
    column_names: tuple[str, ...]
    groups: IntArray | None = None
    group_labels: tuple[str, ...] = ()
    levels: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        x = np.array(self.x, dtype=np.float64)
        y = np.array(self.y, dtype=np.float64)
        if x.ndim != 2:
            raise ValueError("x must be two-dimensional (observations by columns)")
        n, p = x.shape
        if n < 1 or p < 1:
            raise ValueError("a design needs at least one observation and one column")
        if y.shape != (n,):
            raise ValueError(f"y has length {y.size}, expected {n} (one per row of x)")
        if not np.all(np.isfinite(x)):
            raise ValueError("x must contain only finite values")
        if not np.all((y == 0.0) | (y == 1.0)):
            raise ValueError("every response value must be 0 or 1")
        names = tuple(str(c) for c in self.column_names)
        if len(names) != p:
            raise ValueError(f"got {len(names)} column names for {p} columns")
        if len(set(names)) != p:
            raise ValueError("column names must be unique")
        dependent = _dependent_columns(x, names) if np.linalg.matrix_rank(x) < p else []
        if dependent:
            raise ValueError(
                "design matrix is rank deficient; these columns are linear combinations "
                "of earlier ones: " + ", ".join(dependent)
            )
        x.setflags(write=False)
        y.setflags(write=False)
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "column_names", names)
        object.__setattr__(self, "levels", {k: tuple(v) for k, v in self.levels.items()})
        if self.groups is None:
            object.__setattr__(self, "group_labels", ())
            return
        raw = np.asarray(self.groups)
        if raw.dtype.kind not in "iu":
            raise ValueError("groups must be integers")
        groups = raw.astype(np.intp)
        if groups.shape != (n,):
            raise ValueError(f"groups has length {groups.size}, expected {n}")
        n_groups = int(groups.max()) + 1
        if groups.min() < 0 or np.any(np.bincount(groups, minlength=n_groups) == 0):
            raise ValueError("groups must use every cluster index from 0 to n_groups - 1")
        labels = tuple(self.group_labels) or tuple(str(i) for i in range(n_groups))
        if len(labels) != n_groups:
            raise ValueError(f"got {len(labels)} group labels for {n_groups} clusters")
        groups.setflags(write=False)
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "group_labels", labels)

    def __eq__(self, other: object) -> bool:
        """True when ``other`` is a Design with equal fields (arrays element by element)."""
        if type(other) is not type(self):
            return NotImplemented
        return value_key(self) == value_key(other)

    def __hash__(self) -> int:
        """Hash of the field values, consistent with ``==``."""
        return hash(value_key(self))

    @property
    def n_obs(self) -> int:
        """Number of observations."""
        return int(self.x.shape[0])

    @property
    def n_params(self) -> int:
        """Number of columns (fixed effects)."""
        return int(self.x.shape[1])

    @property
    def n_groups(self) -> int:
        """Number of clusters (0 when the design has none)."""
        return len(self.group_labels)

    def with_response(self, y: FloatArray) -> Design:
        """The same design with a different response vector (used by simulations)."""
        return Design(
            x=self.x,
            y=y,
            column_names=self.column_names,
            groups=self.groups,
            group_labels=self.group_labels,
            levels=self.levels,
        )


def flatten_records(
    records: Iterable[Mapping[str, Any]], nested: Sequence[str] = ("conditions",)
) -> list[dict[str, Any]]:
    """Copies of ``records`` with the entries of nested mappings also at the top level.

    With the default ``nested``, a row of ``artifacts/e1/runs.jsonl`` such as
    ``{"task_id": "t1", "conditions": {"M1": "attainable"}, ...}`` becomes
    ``{"task_id": "t1", "conditions": {"M1": "attainable"}, "M1": "attainable", ...}``,
    so a :class:`Formula` can name ``M1`` as a factor and the functions of
    :mod:`receipts.analysis.rates` can use it as a field. The nested mapping is kept
    and the input records are not modified. Flattening is idempotent: a key already at
    the top level with an equal value is left as it is.

    Args:
        records: The records, for example rows of ``artifacts/e1/runs.jsonl``.
        nested: Fields holding mappings to copy up, in order.

    Raises:
        ValueError: A record lacks a nested field, a nested field is not a mapping, or a
            nested key would replace a different value at the top level.
    """
    out: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        row = dict(record)
        for name in nested:
            if name not in record:
                raise ValueError(f"record {index} has no field {name!r} to flatten")
            inner = record[name]
            if not isinstance(inner, Mapping):
                raise ValueError(
                    f"record {index}: field {name!r} is not a mapping (got {type(inner).__name__})"
                )
            for key, value in inner.items():
                if key in row and row[key] != value:
                    raise ValueError(
                        f"record {index}: {name}[{key!r}] = {value!r} would replace "
                        f"the top-level {key!r} = {row[key]!r}"
                    )
                row[key] = value
        out.append(row)
    return out


def _missing(record: Mapping[str, Any], name: str, index: int) -> ValueError:
    """The error for a field absent from a record, naming a nested mapping that has it."""
    holders = [
        str(key) for key, value in record.items() if isinstance(value, Mapping) and name in value
    ]
    hint = ""
    if holders:
        hint = (
            f" (it is inside the nested field {holders[0]!r}; "
            "flatten_records copies it to the top level)"
        )
    return ValueError(f"record {index} has no field {name!r}{hint}")


def _response_value(record: Mapping[str, Any], name: str, index: int) -> float:
    if name not in record:
        raise _missing(record, name, index)
    value = record[name]
    if isinstance(value, bool | np.bool_):
        return float(value)
    if isinstance(value, numbers.Real) and float(value) in (0.0, 1.0):
        return float(value)
    raise ValueError(f"record {index}: response {name!r} must be 0 or 1, got {value!r}")


def _label(record: Mapping[str, Any], name: str, index: int) -> str:
    if name not in record:
        raise _missing(record, name, index)
    value = record[name]
    if value is None:
        raise ValueError(f"record {index} has no value for {name!r}")
    return str(value)


def build_design(records: Sequence[Mapping[str, Any]], formula: Formula) -> Design:
    """Build a treatment-coded :class:`Design` from records (see the module docstring).

    The fields the formula names must be at the top level of each record; for rows of
    ``artifacts/e1/runs.jsonl``, pass ``flatten_records(rows)``.

    Raises:
        ValueError: There are no records; a record lacks a field (the message names a
            nested mapping that holds it) or has an invalid response; a factor has a
            single observed level; a reference level was not observed; or the
            resulting design matrix is rank deficient.
    """
    if not records:
        raise ValueError("no records to build a design from")
    y = np.array(
        [_response_value(r, formula.response, i) for i, r in enumerate(records)], dtype=np.float64
    )
    labels = {f: [_label(r, f, i) for i, r in enumerate(records)] for f in formula.factors}
    levels: dict[str, tuple[str, ...]] = {}
    for name in formula.factors:
        observed = sorted(set(labels[name]))
        if len(observed) < 2:
            raise ValueError(
                f"factor {name!r} has a single observed level {observed[0]!r}; "
                "its effect cannot be estimated"
            )
        ref = formula.reference.get(name, observed[0])
        if ref not in observed:
            raise ValueError(f"reference level {ref!r} of factor {name!r} was not observed")
        levels[name] = (ref, *(lv for lv in observed if lv != ref))
    n = len(records)
    columns: list[FloatArray] = [np.ones(n)]
    names = [INTERCEPT]
    indicators: dict[str, list[tuple[str, FloatArray]]] = {}
    for name in formula.factors:
        values = np.array(labels[name], dtype=object)
        indicators[name] = [(lv, (values == lv).astype(np.float64)) for lv in levels[name][1:]]
        for lv, column in indicators[name]:
            columns.append(column)
            names.append(treatment_column(name, lv))
    for a, b in formula.interactions:
        for la, ca in indicators[a]:
            for lb, cb in indicators[b]:
                columns.append(ca * cb)
                names.append(interaction_column(a, la, b, lb))
    groups: IntArray | None = None
    group_labels: tuple[str, ...] = ()
    if formula.group is not None:
        cluster = [_label(r, formula.group, i) for i, r in enumerate(records)]
        group_labels = tuple(sorted(set(cluster)))
        index = {label: i for i, label in enumerate(group_labels)}
        groups = np.array([index[c] for c in cluster], dtype=np.intp)
    return Design(
        x=np.column_stack(columns),
        y=y,
        column_names=tuple(names),
        groups=groups,
        group_labels=group_labels,
        levels=levels,
    )
