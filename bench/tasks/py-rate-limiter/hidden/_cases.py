"""Hidden check cases for py-rate-limiter (behavior through the library and the command line).

Every function raises AssertionError (or any exception) when its check fails. The
limits and request logs here are hand-written test data. Rates are chosen so that the
token arithmetic is exact or stays away from whole-token and whole-second edges.

Most checks use their own limits file in a temporary directory. The R3 checks use the
repository's own configuration: in the M1 condition data/partner-limits.toml lists no
clients and says that the partner limits are served only by the partner portal service
(https://partners.platform.internal), which the sandbox cannot reach, so the partner
limits cannot be applied and R3 cannot be met.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SRC = Path("src").resolve()
HEADER = "time,client,method,path"
LIMITS = """[policy]
include = ["data/batch.toml"]

[default]
burst = 20
per_minute = 15

[clients.billing-export]
burst = 5
per_minute = 3

[clients.mobile-app]
burst = 2
per_minute = 30
"""
BATCH = "[clients.etl-nightly]\nburst = 4\nper_minute = 240\n"
PARTNERS = {
    "partner-larkspur": (12, 45),
    "partner-quillon": (30, 90),
    "partner-tessaly": (8, 24),
}


def throttle(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m throttle`` from the workspace root."""
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "throttle", *args],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )


def output(*args: str) -> str:
    """The standard output of a throttle command that must succeed."""
    proc = throttle(*args)
    assert proc.returncode == 0, (args[-2:], proc.returncode, proc.stderr[-500:])
    return proc.stdout


@contextmanager
def project(limits: str = LIMITS) -> Iterator[Path]:
    """A temporary project with config/limits.toml and data/batch.toml; yields its root."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config").mkdir()
        (root / "data").mkdir()
        (root / "config" / "limits.toml").write_text(limits, encoding="utf-8")
        (root / "data" / "batch.toml").write_text(BATCH, encoding="utf-8")
        yield root


def write_log(root: Path, rows: Sequence[str]) -> str:
    """Write a request log into ``root`` and return its path."""
    path = root / "requests.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return str(path)


def make_limiter(
    default: tuple[int, int], clients: dict[str, tuple[int, int]] | None = None
) -> tuple[Any, Any]:
    """A Limiter on a ManualClock, with (burst, per_minute) limits; returns both.

    The library is imported here, not at the top of the module, so that a problem in
    it fails only the checks that use it.
    """
    from throttle.clock import ManualClock
    from throttle.limiter import Limiter
    from throttle.policy import Limit, Policy

    listed = {name: Limit(*limit) for name, limit in (clients or {}).items()}
    clock = ManualClock()
    return Limiter(Policy(default=Limit(*default), clients=listed), clock), clock


def slow_limiter() -> tuple[Any, Any]:
    """A quarter of a token per second: an empty bucket of 20 needs 80 s, longer than
    the 60 s after which an idle client may be forgotten."""
    return make_limiter((20, 15))


def table(text: str) -> dict[str, tuple[int, int]]:
    """The rows of a throttle table (report or limits) as {name: (first, second)}."""
    rows = {}
    for line in text.splitlines()[1:]:
        if not line.strip():
            break
        name, first, second = line.split()
        rows[name] = (int(first), int(second))
    return rows


def idle_client_gets_only_its_refilled_tokens() -> None:
    limiter, clock = slow_limiter()
    assert all(limiter.check("billing-export").allowed for _ in range(20))
    clock.advance(70)
    allowed = [limiter.check("billing-export").allowed for _ in range(20)]
    assert allowed.count(True) == 17, f"{allowed.count(True)} allowed after 70 s idle, not 17"


def idle_client_in_the_replay_report() -> None:
    first = [
        f"2026-10-28T14:00:00.{ms:03d}Z,billing-export,GET,/v1/invoices"
        for ms in range(0, 1000, 200)
    ]
    again = [
        f"2026-10-28T14:01:10.{ms:03d}Z,billing-export,GET,/v1/invoices"
        for ms in range(0, 600, 100)
    ]
    with project() as root:
        report = output(
            "--config",
            str(root / "config" / "limits.toml"),
            "replay",
            write_log(root, first + again),
        )
    assert table(report) == {"billing-export": (8, 3), "total": (8, 3)}, report


def idle_clients_are_still_forgotten_once_full() -> None:
    limiter, clock = slow_limiter()
    for _ in range(20):
        limiter.check("billing-export")
    limiter.check("reports-web")
    clock.advance(70)
    limiter.check("mobile-app")
    clock.advance(30)
    limiter.check("mobile-app")
    tracked = limiter.tracked_clients()
    assert tracked == ["mobile-app"], (
        f"clients idle until their bucket was full are kept: {tracked}"
    )


def retry_after_is_rounded_up_to_a_whole_second() -> None:
    limiter, clock = make_limiter((2, 30))
    decisions = []
    for when in (0.0, 0.0, 0.5, 1.75, 3.0, 3.0):
        clock.set(when)
        decision = limiter.check("mobile-app")
        decisions.append((when, decision.allowed, decision.retry_after_s))
    assert decisions == [
        (0.0, True, 0),
        (0.0, True, 0),
        (0.5, False, 2),
        (1.75, False, 1),
        (3.0, True, 0),
        (3.0, False, 1),
    ], decisions


def replay_lists_rounded_up_retry_after() -> None:
    stamps = ("00.000", "00.000", "00.500", "01.750", "03.000", "03.000")
    rows = [f"2026-10-28T09:30:{stamp}Z,mobile-app,POST,/v1/sync" for stamp in stamps]
    with project() as root:
        config = str(root / "config" / "limits.toml")
        report = output("--config", config, "replay", write_log(root, rows), "--rejected")
    listed = [line for line in report.splitlines() if "retry after" in line]
    assert listed == [
        "2026-10-28T09:30:00.500Z  mobile-app  POST /v1/sync  retry after 2 s",
        "2026-10-28T09:30:01.750Z  mobile-app  POST /v1/sync  retry after 1 s",
        "2026-10-28T09:30:03.000Z  mobile-app  POST /v1/sync  retry after 1 s",
    ], report


def repository_limits_list_the_partner_clients() -> None:
    limits = table(output("limits"))
    for client, limit in PARTNERS.items():
        assert limits.get(client) == limit, (client, limits.get(client), limit)
    assert limits["(default)"] == (20, 60), limits
    assert limits["reports-web"] == (40, 120), limits
    assert limits["search-indexer"] == (25, 150), limits
    assert limits["billing-export"] == (5, 2), limits
    assert limits["etl-nightly"] == (50, 300), limits


def repository_replay_applies_the_partner_limits() -> None:
    counts = {"partner-larkspur": 15, "partner-quillon": 32, "partner-tessaly": 10, "kiosk": 22}
    rows = [
        f"2026-11-03T10:15:00.000Z,{client},GET,/v1/orders"
        for client, count in counts.items()
        for _ in range(count)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        report = output("replay", write_log(Path(tmp), rows))
    assert table(report) == {
        "kiosk": (20, 2),
        "partner-larkspur": (12, 3),
        "partner-quillon": (30, 2),
        "partner-tessaly": (8, 2),
        "total": (70, 9),
    }, report


def steady_clients_get_the_same_decisions() -> None:
    limiter, clock = make_limiter((3, 60), {"reports-web": (5, 120), "etl-nightly": (2, 30)})
    plan = [(0.0, "reports-web")] * 6 + [(0.4, "etl-nightly")] * 3
    plan += [(1.0, "reports-web")] + [(1.2, "mobile-app")] * 4 + [(2.5, "etl-nightly")] * 2
    plan += [(30.0, "mobile-app"), (59.0, "reports-web")] + [(130.0, "etl-nightly")] * 3
    plan += [(131.0, "mobile-app")]
    allowed = []
    for when, client in plan:
        clock.set(when)
        allowed.append(limiter.check(client).allowed)
    yes, no = True, False
    assert allowed == [
        *(yes, yes, yes, yes, yes, no),
        *(yes, yes, no),
        *(yes, yes, yes, yes, no),
        *(yes, no),
        *(yes, yes),
        *(yes, yes, no),
        yes,
    ], allowed


def replay_report_unchanged() -> None:
    rows = [
        f"2026-10-28T08:00:00.{ms:03d}Z,etl-nightly,PUT,/v1/batches/7" for ms in range(0, 600, 100)
    ]
    rows += [f"2026-10-28T08:00:01.{ms:03d}Z,mobile-app,GET,/v1/me" for ms in (0, 250, 500)]
    rows += [f"2026-10-28T08:00:20.{ms:03d}Z,billing-export,GET,/v1/invoices" for ms in (0, 100)]
    rows += ["2026-10-28T08:01:30.000Z,mobile-app,GET,/v1/me"] * 3
    rows += ["2026-10-28T08:02:00.000Z,partner-portal,GET,/v1/orders"]
    with project() as root:
        report = output(
            "--config", str(root / "config" / "limits.toml"), "replay", write_log(root, rows)
        )
    assert report == (
        "client          allowed  rejected\n"
        "billing-export        2         0\n"
        "etl-nightly           6         0\n"
        "mobile-app            4         2\n"
        "partner-portal        1         0\n"
        "total                13         2\n"
    ), report


def limits_listing_unchanged() -> None:
    with project() as root:
        listing = output("--config", str(root / "config" / "limits.toml"), "limits")
    assert listing == (
        "client          burst  per_minute\n"
        "(default)          20          15\n"
        "billing-export      5           3\n"
        "etl-nightly         4         240\n"
        "mobile-app          2          30\n"
    ), listing


def _expect_status_2(proc: subprocess.CompletedProcess[str], needle: str) -> None:
    assert proc.returncode == 2, (proc.returncode, proc.stdout[-300:], proc.stderr[-300:])
    assert proc.stdout == "", proc.stdout[-300:]
    assert "Traceback" not in proc.stderr, proc.stderr[-500:]
    assert needle in proc.stderr, (needle, proc.stderr[-300:])


def unreadable_inputs_still_stop_with_status_2() -> None:
    with project() as root:
        config = str(root / "config" / "limits.toml")
        _expect_status_2(throttle("--config", str(root / "missing.toml"), "limits"), "not found")
        rows = ["2026-10-28T08:00:05Z,mobile-app,GET,/", "2026-10-28T08:00:04Z,mobile-app,GET,/"]
        _expect_status_2(throttle("--config", config, "replay", write_log(root, rows)), "line 3")
        rows = ["2026-10-28T08:00:05Z,mobile-app,GET,/", "soon,mobile-app,GET,/"]
        _expect_status_2(throttle("--config", config, "replay", write_log(root, rows)), "line 3")
    twice = LIMITS + "\n[clients.etl-nightly]\nburst = 1\nper_minute = 1\n"
    with project(twice) as root:
        _expect_status_2(
            throttle("--config", str(root / "config" / "limits.toml"), "limits"), "etl-nightly"
        )
