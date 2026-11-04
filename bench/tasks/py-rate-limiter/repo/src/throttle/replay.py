"""Replay a gateway request log through the limiter and count the decisions per client.

A request log is CSV with a header row::

    time,client,method,path
    2026-10-28T14:00:00.000Z,billing-export,GET,/v1/invoices

``time`` is an ISO 8601 time with ``Z`` or an offset, and the rows are in time order.
The replay moves a manual clock to each request's time, so it makes the decisions the
gateway would have made.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from throttle.clock import ManualClock
from throttle.limiter import IDLE_TIMEOUT_S, Limiter
from throttle.policy import Policy

HEADER = ("time", "client", "method", "path")


class LogError(ValueError):
    """A request log that cannot be replayed."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


@dataclass(frozen=True)
class Request:
    """One logged request; ``stamp`` is its time as written in the log."""

    line: int
    stamp: str
    when: datetime
    client: str
    method: str
    path: str


def parse_time(text: str) -> datetime:
    """An ISO 8601 time that names its offset (``Z`` for UTC, or ``+01:00``)."""
    value = datetime.fromisoformat(text.strip())
    if value.tzinfo is None:
        raise ValueError(f"time {text!r} has no offset (add Z for UTC)")
    return value


def parse_log(text: str) -> list[Request]:
    """The requests of a log, in order; blank lines are skipped.

    Raises:
        LogError: The header is missing, or a row is malformed or earlier than the
            row before it.
    """
    reader = csv.reader(io.StringIO(text))
    requests: list[Request] = []
    header_seen = False
    for row in reader:
        line = reader.line_num
        if not any(item.strip() for item in row):
            continue
        if not header_seen:
            if tuple(item.strip() for item in row) != HEADER:
                raise LogError(line, f"expected the header {','.join(HEADER)}")
            header_seen = True
            continue
        if len(row) != len(HEADER):
            raise LogError(line, f"expected {len(HEADER)} fields, got {len(row)}")
        stamp, client, method, path = (item.strip() for item in row)
        try:
            when = parse_time(stamp)
        except ValueError:
            raise LogError(line, f"invalid time {stamp!r}") from None
        if not client:
            raise LogError(line, "missing client")
        if requests and when < requests[-1].when:
            raise LogError(line, f"time {stamp} goes backwards (the log must be in time order)")
        requests.append(Request(line, stamp, when, client, method, path))
    if not header_seen:
        raise LogError(1, "the log is empty (expected a header row)")
    return requests


def read_log(path: Path) -> list[Request]:
    """Read a request log file (UTF-8)."""
    return parse_log(path.read_text(encoding="utf-8"))


@dataclass
class ClientTotals:
    """How many requests of one client were allowed and rejected."""

    allowed: int = 0
    rejected: int = 0


@dataclass(frozen=True)
class Rejection:
    """A rejected request and the Retry-After the gateway sent with it."""

    request: Request
    retry_after_s: int


@dataclass
class ReplayResult:
    """The totals per client and every rejection, in log order."""

    totals: dict[str, ClientTotals] = field(default_factory=dict)
    rejections: list[Rejection] = field(default_factory=list)


def replay(
    requests: Sequence[Request], policy: Policy, idle_timeout_s: float = IDLE_TIMEOUT_S
) -> ReplayResult:
    """Run ``requests`` through a fresh limiter whose clock follows the log."""
    result = ReplayResult()
    if not requests:
        return result
    first = requests[0].when
    clock = ManualClock()
    limiter = Limiter(policy, clock, idle_timeout_s)
    for request in requests:
        clock.set((request.when - first).total_seconds())
        decision = limiter.check(request.client)
        totals = result.totals.setdefault(request.client, ClientTotals())
        if decision.allowed:
            totals.allowed += 1
        else:
            totals.rejected += 1
            result.rejections.append(Rejection(request, decision.retry_after_s))
    return result


def render_report(result: ReplayResult, rejected: bool = False) -> str:
    """The totals table; with ``rejected``, also one line per rejected request."""
    width = max([len("client"), *(len(name) for name in result.totals)])
    lines = [f"{'client':<{width}}  {'allowed':>7}  {'rejected':>8}"]
    for name in sorted(result.totals):
        totals = result.totals[name]
        lines.append(f"{name:<{width}}  {totals.allowed:>7}  {totals.rejected:>8}")
    allowed = sum(totals.allowed for totals in result.totals.values())
    refused = sum(totals.rejected for totals in result.totals.values())
    lines.append(f"{'total':<{width}}  {allowed:>7}  {refused:>8}")
    if rejected:
        lines.append("")
        lines.append("rejected requests:" if result.rejections else "rejected requests: none")
        for item in result.rejections:
            request = item.request
            lines.append(
                f"{request.stamp}  {request.client}  {request.method} {request.path}"
                f"  retry after {item.retry_after_s} s"
            )
    return "\n".join(lines) + "\n"
