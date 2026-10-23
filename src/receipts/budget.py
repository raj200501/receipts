"""Usage caps and the usage ledger (docs/BUILD_BRIEF.md section 8).

``budget.toml`` holds the caps. The brief's defaults are ceilings: a cap may be
lowered and never raised, and ``cash_usd`` is always 0. ``CAP_SHARE`` (set
when two projects share one plan) scales every ``claude_*`` cap down. Every
model call is logged to ``artifacts/usage/ledger.jsonl``; this module counts
that ledger against the caps.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path

CAP_KEYS: tuple[str, ...] = (
    "cash_usd",
    "claude_agent_runs_per_day",
    "claude_agent_max_turns",
    "claude_single_calls_per_day",
    "claude_review_runs_per_day",
    "local_model_max_params_b",
    "disk_floor_gb",
)
CLAUDE_CAP_KEYS: tuple[str, ...] = tuple(k for k in CAP_KEYS if k.startswith("claude_"))

# Caps where a larger value is *safer*. Lowering these would loosen the budget,
# so "never raise a cap" means "never lower" for them.
FLOOR_KEYS: frozenset[str] = frozenset({"disk_floor_gb"})

# Usage-ledger ``kind`` values and the daily cap that counts them.
KIND_TO_DAILY_CAP: Mapping[str, str] = {
    "agent_run": "claude_agent_runs_per_day",
    "single_call": "claude_single_calls_per_day",
    "review_run": "claude_review_runs_per_day",
}


class BudgetError(ValueError):
    """Raised when budget configuration is malformed or unsafe."""


@dataclass(frozen=True)
class Caps:
    """The caps from ``budget.toml``."""

    cash_usd: float
    claude_agent_runs_per_day: int
    claude_agent_max_turns: int
    claude_single_calls_per_day: int
    claude_review_runs_per_day: int
    local_model_max_params_b: float
    disk_floor_gb: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Caps:
        """Build caps from a parsed TOML mapping, rejecting missing or extra keys."""
        missing = [k for k in CAP_KEYS if k not in data]
        extra = sorted(set(data) - set(CAP_KEYS))
        if missing or extra:
            raise BudgetError(f"budget keys: missing={missing} unexpected={extra}")
        values: dict[str, float] = {}
        for key in CAP_KEYS:
            value = data[key]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise BudgetError(f"{key} must be a number")
            if value < 0:
                raise BudgetError(f"{key} must be non-negative")
            values[key] = value
        return cls(
            cash_usd=float(values["cash_usd"]),
            claude_agent_runs_per_day=int(values["claude_agent_runs_per_day"]),
            claude_agent_max_turns=int(values["claude_agent_max_turns"]),
            claude_single_calls_per_day=int(values["claude_single_calls_per_day"]),
            claude_review_runs_per_day=int(values["claude_review_runs_per_day"]),
            local_model_max_params_b=float(values["local_model_max_params_b"]),
            disk_floor_gb=float(values["disk_floor_gb"]),
        )

    def as_dict(self) -> dict[str, float]:
        """Return the caps as a plain mapping keyed by ``CAP_KEYS``."""
        return {f.name: float(getattr(self, f.name)) for f in fields(self)}

    def effective(self, cap_share: float) -> Caps:
        """Return caps with every ``claude_*`` cap scaled by ``cap_share`` (rounded down)."""
        share = validate_cap_share(cap_share)
        return Caps(
            cash_usd=self.cash_usd,
            claude_agent_runs_per_day=math.floor(self.claude_agent_runs_per_day * share),
            claude_agent_max_turns=math.floor(self.claude_agent_max_turns * share),
            claude_single_calls_per_day=math.floor(self.claude_single_calls_per_day * share),
            claude_review_runs_per_day=math.floor(self.claude_review_runs_per_day * share),
            local_model_max_params_b=self.local_model_max_params_b,
            disk_floor_gb=self.disk_floor_gb,
        )


def validate_cap_share(value: float) -> float:
    """Return ``value`` if it is a valid CAP_SHARE in [0, 1], else raise BudgetError."""
    if math.isnan(value) or value < 0 or value > 1:
        raise BudgetError("CAP_SHARE must be between 0 and 1; it can only lower caps")
    return value


def parse_cap_share(env: Mapping[str, str]) -> float:
    """Read CAP_SHARE from ``env``; unset means 1.0, invalid values raise BudgetError."""
    raw = env.get("CAP_SHARE")
    if raw is None or raw.strip() == "":
        return 1.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise BudgetError(f"CAP_SHARE is not a number: {raw!r}") from exc
    return validate_cap_share(value)


def load_caps(path: Path) -> Caps:
    """Load and validate ``budget.toml``."""
    with path.open("rb") as handle:
        return Caps.from_mapping(tomllib.load(handle))


_BRIEF_TOML = re.compile(r"Caps live in `budget\.toml`.*?```toml\n(.*?)```", re.DOTALL)


def parse_brief_defaults(brief_text: str) -> Caps:
    """Extract the default caps from the brief's section 8 TOML block."""
    match = _BRIEF_TOML.search(brief_text)
    if match is None:
        raise BudgetError("could not find the budget.toml defaults block in the brief")
    return Caps.from_mapping(tomllib.loads(match.group(1)))


def check_against_defaults(caps: Caps, defaults: Caps) -> list[str]:
    """Return a violation for ``cash_usd != 0`` and for every cap looser than the brief."""
    problems: list[str] = []
    if caps.cash_usd != 0:
        problems.append(f"cash_usd is {caps.cash_usd:g}; it must be 0")
    current, ceiling = caps.as_dict(), defaults.as_dict()
    for key in CAP_KEYS:
        if key == "cash_usd":
            continue
        looser = current[key] < ceiling[key] if key in FLOOR_KEYS else current[key] > ceiling[key]
        if looser:
            problems.append(f"{key} = {current[key]:g} is looser than the brief's {ceiling[key]:g}")
    return problems


def lower_cap(path: Path, key: str, new_value: float) -> bool:
    """Lower ``key`` in ``budget.toml`` in place, keeping comments. Never raises a cap.

    Returns:
        True if the file changed, False if the current value was already at or below.
    """
    if key not in CAP_KEYS or key == "cash_usd" or key in FLOOR_KEYS:
        raise BudgetError(f"{key} cannot be lowered with lower_cap")
    caps = load_caps(path)
    if new_value >= caps.as_dict()[key]:
        return False
    text = path.read_text(encoding="utf-8")
    rendered = str(int(new_value)) if float(new_value).is_integer() else f"{new_value:g}"
    pattern = re.compile(rf"^({re.escape(key)}\s*=\s*)[0-9.]+", re.MULTILINE)
    updated, count = pattern.subn(lambda m: m.group(1) + rendered, text, count=1)
    if count != 1:
        raise BudgetError(f"could not find {key} in {path}")
    path.write_text(updated, encoding="utf-8")
    return True


@dataclass(frozen=True)
class UsageRecord:
    """One logged model call from ``artifacts/usage/ledger.jsonl``."""

    day: str
    backend: str
    kind: str
    cap_share: float
    cash_usd: float
    cache_hit: bool

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> UsageRecord:
        """Parse one ledger line, raising BudgetError on missing or mistyped fields."""
        try:
            day, backend, kind = str(data["day"]), str(data["backend"]), str(data["kind"])
            cap_share = data.get("cap_share", 1.0)
            cash = data.get("cash_usd", 0.0)
            cache_hit = data.get("cache_hit", False)
        except KeyError as exc:
            raise BudgetError(f"usage record missing {exc}") from exc
        if not isinstance(cap_share, int | float) or not isinstance(cash, int | float):
            raise BudgetError("usage record cap_share and cash_usd must be numbers")
        if not isinstance(cache_hit, bool):
            raise BudgetError("usage record cache_hit must be a boolean")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise BudgetError(f"usage record day must be YYYY-MM-DD, got {day!r}")
        return cls(day, backend, kind, float(cap_share), float(cash), cache_hit)


def read_usage(path: Path) -> list[UsageRecord]:
    """Read the usage ledger; a missing file means no usage yet."""
    if not path.is_file():
        return []
    records: list[UsageRecord] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BudgetError(f"{path}:{number}: invalid JSON") from exc
        if not isinstance(data, dict):
            raise BudgetError(f"{path}:{number}: expected an object")
        records.append(UsageRecord.from_json(data))
    return records


def check_usage(records: Iterable[UsageRecord], caps: Caps) -> list[str]:
    """Return a violation for any cash spend and any day that exceeded a Claude cap.

    Cache hits make no model call and do not count. The cap for a day uses the
    smallest CAP_SHARE recorded that day, so a shared-plan day is held to the
    stricter limit.
    """
    problems: list[str] = []
    counts: Counter[tuple[str, str]] = Counter()
    shares: dict[str, float] = {}
    for record in records:
        if record.cash_usd != 0:
            problems.append(f"{record.day}: a call recorded cash_usd = {record.cash_usd:g}")
        if record.backend != "claude" or record.cache_hit:
            continue
        if record.kind not in KIND_TO_DAILY_CAP:
            problems.append(f"{record.day}: unknown Claude call kind {record.kind!r}")
            continue
        counts[(record.day, record.kind)] += 1
        shares[record.day] = min(shares.get(record.day, 1.0), record.cap_share)
    for (day, kind), count in sorted(counts.items()):
        cap_key = KIND_TO_DAILY_CAP[kind]
        limit = caps.effective(shares[day]).as_dict()[cap_key]
        if count > limit:
            problems.append(f"{day}: {count} {kind} calls exceed {cap_key} = {limit:g}")
    return problems


def total_cash(records: Iterable[UsageRecord]) -> float:
    """Return the total cash recorded in the usage ledger (it must stay 0)."""
    return sum(record.cash_usd for record in records)
