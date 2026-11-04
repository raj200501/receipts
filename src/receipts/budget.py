"""Usage caps and the usage ledger (docs/BUILD_BRIEF.md section 8).

``budget.toml`` holds the caps. The brief's defaults are ceilings: a cap may be
lowered and never raised, and ``cash_usd`` is always 0. ``CAP_SHARE`` (set
when two projects share one plan) scales every ``claude_*`` cap down. Every
model call is logged to ``artifacts/usage/ledger.jsonl``; this module counts
that ledger against the caps: cash, the daily Claude caps, the turns of each
multi-turn Claude run (``num_turns``), and the size of each local model (read
from its pinned name, such as ``qwen2.5-coder-7b-instruct-q4km``).
``disk_floor_gb`` governs downloads, which are not model calls, so the ledger
cannot show it.
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
# Claude kinds that are multi-turn headless runs, held to claude_agent_max_turns.
MULTI_TURN_KINDS: frozenset[str] = frozenset({"agent_run", "review_run"})
# A parameter count in billions in a model name: "7b" in qwen2.5-coder-7b, "1.5b", "8B",
# and "8x7b" (8 experts of 7B each, the GGUF size-label form). "a3b" in qwen3-30b-a3b
# and "e4b" in gemma-3n-e4b are active or effective sizes, smaller than the total; the
# marker is a token of its own or glued to a size ("21BA3B"). Other scales are not
# read: "128k" and "1m" are usually context lengths and "3T" training tokens.
_MODEL_SIZE = re.compile(
    r"""
    (?: (?P<marker> (?: (?<![a-z0-9]) | (?<=\db) ) [ae] ) | (?<![\d.]) )
    (?: (?P<experts>\d+) [x\N{MULTIPLICATION SIGN}] )?
    (?P<count>\d+(?:\.\d+)?) b
    (?! (?![ae]\d) [a-z0-9] )
    """,
    re.IGNORECASE | re.VERBOSE,
)
# An expert count as a token of its own: "16E" in Llama-4-Scout-17B-16E, where the
# size beside it (17B) is the active size.
_EXPERT_COUNT = re.compile(r"(?i)(?<![a-z0-9.])(?:[2-9]|[1-9]\d+)e(?![a-z0-9])")
_HEX64 = re.compile(r"[0-9a-f]{64}")


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


def load_launch_cap_share(path: Path) -> float:
    """Read ``cap_share`` from ``launch.toml``; a missing file or key means 1.0."""
    if not path.is_file():
        return 1.0
    with path.open("rb") as handle:
        value = tomllib.load(handle).get("cap_share", 1.0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BudgetError("launch.toml cap_share must be a number")
    return validate_cap_share(float(value))


def effective_cap_share(env: Mapping[str, str], launch_path: Path) -> float:
    """Return the stricter of the CAP_SHARE environment variable and ``launch.toml``."""
    return min(parse_cap_share(env), load_launch_cap_share(launch_path))


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


def recorded_digest(text: str) -> str:
    """Return the SHA-256 at the start of a ``sha256sum``-style line, else raise BudgetError."""
    token = text.split()[0] if text.split() else ""
    if not _HEX64.fullmatch(token):
        raise BudgetError("expected a line that starts with a 64-character lowercase SHA-256")
    return token


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
    model: str = ""
    num_turns: int | None = None

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
        model = data.get("model", "")
        turns = data.get("num_turns")
        if not isinstance(cap_share, int | float) or not isinstance(cash, int | float):
            raise BudgetError("usage record cap_share and cash_usd must be numbers")
        if not isinstance(cache_hit, bool):
            raise BudgetError("usage record cache_hit must be a boolean")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise BudgetError(f"usage record day must be YYYY-MM-DD, got {day!r}")
        if not isinstance(model, str):
            raise BudgetError("usage record model must be a string")
        if turns is not None and (isinstance(turns, bool) or not isinstance(turns, int)):
            raise BudgetError("usage record num_turns must be an integer")
        if turns is not None and turns < 0:
            raise BudgetError("usage record num_turns must be non-negative")
        return cls(day, backend, kind, float(cap_share), float(cash), cache_hit, model, turns)


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


def model_params_b(name: str) -> float | None:
    """Return the total parameter count in billions named in a model name, or None.

    A mixture-of-experts name is judged by its total, never by an expert or
    active size. ``NxMb`` (N experts of M billion) reads as N times M, an upper
    bound because experts share some layers, and the largest reading wins:
    ``mixtral-8x7b`` reads as 56 and ``qwen3-30b-a3b`` as 30. An active or
    effective size is not a total, so a name with only that, such as
    ``qwen1.5-moe-a2.7b``, returns None and the caller fails closed. So does a
    name with an expert count of its own, such as ``llama-4-scout-17b-16e``,
    unless it also marks an active size: its plain size is the active one.
    """
    sizes = list(_MODEL_SIZE.finditer(name))
    has_active = any(m.group("marker") for m in sizes)
    plain_is_total = has_active or _EXPERT_COUNT.search(name) is None
    totals = [
        float(m.group("experts") or 1) * float(m.group("count"))
        for m in sizes
        if m.group("marker") is None and (m.group("experts") or plain_is_total)
    ]
    return max(totals) if totals else None


def _multi_turn_runs(records: Iterable[UsageRecord]) -> list[UsageRecord]:
    return [
        r
        for r in records
        if r.backend == "claude" and not r.cache_hit and r.kind in MULTI_TURN_KINDS
    ]


def runs_without_turns(records: Iterable[UsageRecord]) -> int:
    """Count multi-turn Claude runs whose record has no ``num_turns`` (turns unverified)."""
    return sum(1 for r in _multi_turn_runs(records) if r.num_turns is None)


def _check_turns(records: Iterable[UsageRecord], caps: Caps) -> list[str]:
    """No multi-turn Claude run recorded more turns than its effective cap."""
    over: dict[tuple[str, str, int], list[int]] = {}
    for record in _multi_turn_runs(records):
        limit = caps.effective(record.cap_share).claude_agent_max_turns
        if record.num_turns is not None and record.num_turns > limit:
            over.setdefault((record.day, record.kind, limit), []).append(record.num_turns)
    return [
        f"{day}: {len(turns)} {kind} run(s) took more than claude_agent_max_turns = {limit} "
        f"turns (max {max(turns)})"
        for (day, kind, limit), turns in sorted(over.items())
    ]


def _check_local_models(records: Iterable[UsageRecord], caps: Caps) -> list[str]:
    """Every local call names a model within ``local_model_max_params_b``."""
    calls = Counter(r.model for r in records if r.backend == "local" and not r.cache_hit)
    problems: list[str] = []
    for model, count in sorted(calls.items()):
        size = model_params_b(model)
        if size is None:
            problems.append(
                f"local model {model!r} has no total parameter count in its name ({count} call(s))"
            )
        elif size > caps.local_model_max_params_b:
            problems.append(
                f"local model {model!r} ({size:g}B) is above local_model_max_params_b = "
                f"{caps.local_model_max_params_b:g} in {count} call(s)"
            )
    return problems


def check_usage(records: Iterable[UsageRecord], caps: Caps) -> list[str]:
    """Return a violation for any cash spend and any call or day that exceeded a cap.

    Cache hits make no model call and do not count. The daily cap for a day uses
    the smallest CAP_SHARE recorded that day, so a shared-plan day is held to the
    stricter limit; the turn cap of a run uses the share recorded with it.
    """
    records = list(records)
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
    problems += _check_turns(records, caps)
    problems += _check_local_models(records, caps)
    return problems


def total_cash(records: Iterable[UsageRecord]) -> float:
    """Return the total cash recorded in the usage ledger (it must stay 0)."""
    return sum(record.cash_usd for record in records)
