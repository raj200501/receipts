"""The one client wrapper every model call goes through (docs/BUILD_BRIEF.md section 8).

Responsibilities, in order, for each call:

1. Refuse when ``RECEIPTS_OFFLINE=1`` (the offline demo and ship-check use it).
2. For Claude backends, refuse while the billing guard reports anything.
3. Return a cached response when the same request was made before. The cache key
   is the SHA-256 of the canonical request (backend, model, messages, parameters).
   A banked call is never re-run.
4. Refuse when the call would exceed today's cap for its kind, after scaling every
   ``claude_*`` cap by the effective CAP_SHARE.
5. Make the call, then append one record to ``artifacts/usage/ledger.jsonl`` with
   tokens, wall time, cap share, ``cash_usd = 0`` and, for Claude, the API-price
   estimate as ``plan_equivalent_usd`` (never added to cash).

Backends implement :class:`Backend`. This module has no network code of its own.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from receipts import budget, guard
from receipts.ledger.events import canonical_json, sha256_text

CallKind = Literal["agent_run", "single_call", "review_run", "local_call"]


class ClientRefusedError(RuntimeError):
    """Raised when the wrapper refuses a call (offline, billing guard, or cap)."""


@dataclass(frozen=True)
class ModelRequest:
    """One model request.

    Attributes:
        backend: Backend name, e.g. ``"local"`` or ``"claude"``.
        model: Model identifier including revision or file hash.
        messages: Chat messages as ``{"role": ..., "content": ...}`` mappings.
        params: Sampling and other parameters (temperature, max_tokens, seed, ...).
        kind: What the call counts against (``local_call`` counts against no Claude cap).
        purpose: Free-text label for the usage ledger, e.g. ``"e1:minimal-agent step"``.
    """

    backend: str
    model: str
    messages: Sequence[Mapping[str, str]]
    params: Mapping[str, Any] = field(default_factory=dict)
    kind: CallKind = "local_call"
    purpose: str = ""

    def cache_key(self) -> str:
        """Content hash of everything that determines the response."""
        body = {
            "backend": self.backend,
            "model": self.model,
            "messages": [dict(m) for m in self.messages],
            "params": dict(self.params),
        }
        return sha256_text(canonical_json(body))


@dataclass(frozen=True)
class ModelResponse:
    """One model response, as cached and returned."""

    text: str
    input_tokens: int
    output_tokens: int
    wall_s: float
    finish_reason: str
    plan_equivalent_usd: float = 0.0
    raw: Mapping[str, Any] = field(default_factory=dict)
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the cacheable form (``cache_hit`` is not stored)."""
        return {
            "text": self.text,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_s": self.wall_s,
            "finish_reason": self.finish_reason,
            "plan_equivalent_usd": self.plan_equivalent_usd,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, cache_hit: bool) -> ModelResponse:
        """Rebuild a response from its cached form."""
        return cls(
            text=str(data["text"]),
            input_tokens=int(data["input_tokens"]),
            output_tokens=int(data["output_tokens"]),
            wall_s=float(data["wall_s"]),
            finish_reason=str(data["finish_reason"]),
            plan_equivalent_usd=float(data.get("plan_equivalent_usd", 0.0)),
            raw=dict(data.get("raw", {})),
            cache_hit=cache_hit,
        )


class Backend(Protocol):
    """A model backend. ``complete`` performs exactly one model call."""

    @property
    def name(self) -> str:
        """Backend name recorded in the usage ledger."""
        ...

    @property
    def is_claude(self) -> bool:
        """True when calls are served by Claude (billing guard and caps apply)."""
        ...

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Perform the call."""
        ...


def _today(clock: Callable[[], float]) -> str:
    return dt.datetime.fromtimestamp(clock(), tz=dt.UTC).strftime("%Y-%m-%d")


class ModelClient:
    """Cap-enforcing, caching, usage-logging front door for every model call.

    Args:
        root: Repository root (for ``budget.toml``, ``launch.toml``, the usage ledger).
        backends: Available backends by name.
        cache_dir: Response cache directory (outside version control).
        env: Environment for CAP_SHARE, RECEIPTS_OFFLINE, and the billing guard.
        clock: Time source (seconds since the epoch).
        guard_check: Returns billing-guard problems; defaults to the real guard.
    """

    def __init__(
        self,
        root: Path,
        backends: Mapping[str, Backend],
        cache_dir: Path,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
        guard_check: Callable[[], Sequence[guard.GuardProblem]] | None = None,
    ) -> None:
        self.root = root
        self.backends = dict(backends)
        self.cache_dir = cache_dir
        self.env = dict(os.environ if env is None else env)
        self.clock = clock
        self.usage_path = root / "artifacts" / "usage" / "ledger.jsonl"
        self._lock = threading.Lock()
        self._guard_check = guard_check or (lambda: guard.billing_guard_problems(repo=root))

    def caps(self) -> budget.Caps:
        """Effective caps today: ``budget.toml`` scaled by the effective cap share."""
        caps = budget.load_caps(self.root / "budget.toml")
        return caps.effective(self.cap_share())

    def cap_share(self) -> float:
        """Stricter of the CAP_SHARE environment variable and ``launch.toml``."""
        return budget.effective_cap_share(self.env, self.root / "launch.toml")

    def used_today(self, kind: str) -> int:
        """Claude calls of ``kind`` already logged today (cache hits excluded)."""
        day = _today(self.clock)
        records = budget.read_usage(self.usage_path)
        return sum(
            1
            for r in records
            if r.day == day and r.backend == "claude" and r.kind == kind and not r.cache_hit
        )

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def _check_cap(self, request: ModelRequest) -> None:
        cap_key = budget.KIND_TO_DAILY_CAP.get(request.kind)
        if cap_key is None:
            raise ClientRefusedError(f"Claude calls need a capped kind, got {request.kind!r}")
        limit = self.caps().as_dict()[cap_key]
        used = self.used_today(request.kind)
        if used + 1 > limit:
            raise ClientRefusedError(f"{cap_key} reached: {used} of {limit:g} used today")

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Serve ``request`` from cache or make the call, enforcing every rule above."""
        if self.env.get("RECEIPTS_OFFLINE") == "1":
            raise ClientRefusedError("RECEIPTS_OFFLINE=1: model calls are disabled")
        backend = self.backends.get(request.backend)
        if backend is None:
            raise ClientRefusedError(f"unknown backend {request.backend!r}")
        if backend.is_claude:
            problems = self._guard_check()
            if problems:
                names = ", ".join(p.name for p in problems)
                raise ClientRefusedError(f"billing guard tripped ({names}); Claude call refused")
        key = request.cache_key()
        cached = self._cache_path(key)
        if cached.is_file():
            response = ModelResponse.from_dict(
                json.loads(cached.read_text(encoding="utf-8")), cache_hit=True
            )
            self._log(request, backend, response)
            return response
        if backend.is_claude:
            self._check_cap(request)
        response = backend.complete(request)
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".tmp")
        tmp.write_text(canonical_json(response.to_dict()), encoding="utf-8")
        tmp.replace(cached)
        self._log(request, backend, response)
        return response

    def begin_claude_run(self, kind: CallKind, model: str, purpose: str) -> None:
        """Check, before a multi-turn Claude run starts, that it may start.

        A headless subject run (or one Claude-in-minimal-agent run) counts once against
        its daily cap, so the check happens here rather than per model call. Raises
        :class:`ClientRefusedError` when offline, when the guard trips, or at the cap.
        """
        if self.env.get("RECEIPTS_OFFLINE") == "1":
            raise ClientRefusedError("RECEIPTS_OFFLINE=1: model calls are disabled")
        problems = self._guard_check()
        if problems:
            names = ", ".join(p.name for p in problems)
            raise ClientRefusedError(f"billing guard tripped ({names}); Claude run refused")
        probe = ModelRequest(backend="claude", model=model, messages=(), kind=kind, purpose=purpose)
        self._check_cap(probe)

    def record_claude_run(
        self,
        kind: CallKind,
        model: str,
        purpose: str,
        *,
        input_tokens: int,
        output_tokens: int,
        wall_s: float,
        plan_equivalent_usd: float,
    ) -> None:
        """Log one finished multi-turn Claude run to the usage ledger (cash is always 0)."""
        request = ModelRequest(
            backend="claude", model=model, messages=(), kind=kind, purpose=purpose
        )
        response = ModelResponse(
            "", input_tokens, output_tokens, wall_s, "run", plan_equivalent_usd=plan_equivalent_usd
        )
        self._log(request, _ClaudeRunMarker(), response)

    def _log(self, request: ModelRequest, backend: Backend, response: ModelResponse) -> None:
        record = {
            "ts": round(self.clock(), 3),
            "day": _today(self.clock),
            "backend": "claude" if backend.is_claude else backend.name,
            "kind": request.kind,
            "model": request.model,
            "purpose": request.purpose,
            "cap_share": self.cap_share(),
            "cash_usd": 0,
            "plan_equivalent_usd": response.plan_equivalent_usd if backend.is_claude else 0.0,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "wall_s": round(response.wall_s, 3),
            "cache_hit": response.cache_hit,
            "cache_key": request.cache_key(),
        }
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.usage_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(record) + "\n")


class _ClaudeRunMarker:
    """Backend stand-in used only to log multi-turn Claude runs."""

    name = "claude"
    is_claude = True

    def complete(self, request: ModelRequest) -> ModelResponse:  # pragma: no cover
        raise ClientRefusedError("a run marker cannot make calls")
