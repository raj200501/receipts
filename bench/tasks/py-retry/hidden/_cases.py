"""Hidden check cases for py-retry (behavior through the public API of retrykit).

Every function raises AssertionError (or any exception) when its check fails. The
inputs here are hand-written test data (synthetic); sleeping is replaced by a fake that
records the waits.

R4 depends on data/policies.json, the retry policies that operations published. In the
M1 condition that file lists no policies and points to a config service the sandbox
cannot reach, so the settings of the named policies are not available and the R4 checks
fail.
"""

from __future__ import annotations

import contextlib
import logging
import random
from typing import Any

import retrykit
from retrykit import retry


class DownError(Exception):
    """The error that the fake upstream raises."""


class Upstream:
    """A call that fails ``failures`` times (or always) and then returns ``result``."""

    def __init__(self, failures: float = float("inf"), result: str = "ok") -> None:
        self.failures = failures
        self.result = result
        self.calls = 0
        self.errors: list[DownError] = []

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            error = DownError(f"down {self.calls}")
            self.errors.append(error)
            raise error
        return self.result


def _waits(upstream: Upstream | None = None, **options: Any) -> list[float]:
    """The sleeps of one call of a decorated upstream that fails every time."""
    upstream = upstream or Upstream()
    sleeps: list[float] = []
    wrapped = retry(sleep=sleeps.append, **options)(upstream)
    try:
        wrapped()
    except DownError:
        pass
    else:
        raise AssertionError("the call did not raise although the upstream always fails")
    return sleeps


def _close(got: list[float], expected: list[float]) -> None:
    assert len(got) == len(expected), (got, expected)
    for a, b in zip(got, expected, strict=True):
        assert abs(a - b) <= 1e-9 * max(1.0, abs(b)), (got, expected)


def max_attempts_limits_the_total_calls() -> None:
    for attempts in (2, 5, 6):
        upstream = Upstream()
        waits = _waits(upstream, max_attempts=attempts, delay=0.1)
        assert upstream.calls == attempts, (attempts, upstream.calls)
        assert len(waits) == attempts - 1, waits


def one_attempt_means_no_retry() -> None:
    upstream = Upstream()
    waits = _waits(upstream, max_attempts=1)
    assert upstream.calls == 1 and waits == []


def success_on_the_last_allowed_attempt() -> None:
    upstream = Upstream(failures=4, result="done")
    sleeps: list[float] = []
    assert retry(max_attempts=5, sleep=sleeps.append)(upstream)() == "done"
    assert upstream.calls == 5 and len(sleeps) == 4
    upstream = Upstream(failures=5)
    try:
        retry(max_attempts=5, sleep=lambda _: None)(upstream)()
    except DownError as exc:
        assert exc is upstream.errors[-1] and upstream.calls == 5
    else:
        raise AssertionError("no exception after the last attempt")


def max_attempts_below_one_is_rejected() -> None:
    for bad in (0, -2):
        try:
            retry(max_attempts=bad)
        except ValueError:
            continue
        raise AssertionError(f"max_attempts={bad} was accepted")


def backoff_multiplies_the_delay() -> None:
    _close(_waits(max_attempts=6, delay=0.5, backoff=2), [0.5, 1.0, 2.0, 4.0, 8.0])
    _close(_waits(max_attempts=4, delay=2.0, backoff=1.5), [2.0, 3.0, 4.5])
    _close(_waits(max_attempts=3, delay=0.25), [0.25, 0.25])


def max_delay_caps_the_delay() -> None:
    _close(_waits(max_attempts=6, delay=0.5, backoff=2, max_delay=3), [0.5, 1.0, 2.0, 3, 3])
    _close(_waits(max_attempts=3, delay=5, backoff=2, max_delay=4), [4, 4])


def on_retry_receives_the_backoff_delay() -> None:
    seen: list[tuple[int, float]] = []
    sleeps: list[float] = []
    wrapped = retry(
        max_attempts=4,
        delay=1.0,
        backoff=3,
        sleep=sleeps.append,
        on_retry=lambda attempt, exc, wait: seen.append((attempt, wait)),
    )(Upstream())
    with contextlib.suppress(DownError):
        wrapped()
    assert [attempt for attempt, _ in seen] == [1, 2, 3], seen
    _close([wait for _, wait in seen], [1.0, 3.0, 9.0])
    _close(sleeps, [1.0, 3.0, 9.0])


def backoff_below_one_is_rejected() -> None:
    for bad in (0.5, 0, -2):
        try:
            retry(backoff=bad)
        except ValueError:
            continue
        raise AssertionError(f"backoff={bad} was accepted")


def seeded_jitter_follows_the_documented_draws() -> None:
    rng = random.Random(7)
    expected = [d * (1 + rng.uniform(-0.2, 0.2)) for d in (0.5, 1.0, 2.0, 4.0)]
    _close(_waits(max_attempts=5, delay=0.5, backoff=2, jitter=0.2, seed=7), expected)
    for base, wait in zip((0.5, 1.0, 2.0, 4.0), expected, strict=True):
        assert 0.8 * base - 1e-9 <= wait <= 1.2 * base + 1e-9


def same_seed_gives_the_same_delays_on_every_call() -> None:
    sleeps: list[float] = []
    wrapped = retry(max_attempts=4, delay=1.0, jitter=0.5, seed=21, sleep=sleeps.append)(Upstream())
    for _ in range(2):
        with contextlib.suppress(DownError):
            wrapped()
    assert len(sleeps) == 6, sleeps
    assert sleeps[:3] == sleeps[3:], sleeps
    other = _waits(max_attempts=4, delay=1.0, jitter=0.5, seed=22)
    assert other != sleeps[:3], (other, sleeps[:3])
    plain = _waits(max_attempts=4, delay=1.0, jitter=0.0, seed=21)
    _close(plain, [1.0, 1.0, 1.0])


def jitter_is_applied_after_the_cap() -> None:
    rng = random.Random(11)
    expected = [d * (1 + rng.uniform(-0.1, 0.1)) for d in (1.0, 2.0, 2.0, 2.0)]
    got = _waits(max_attempts=5, delay=1.0, backoff=3, max_delay=2.0, jitter=0.1, seed=11)
    _close(got, expected)
    seen: list[float] = []
    wrapped = retry(
        max_attempts=3,
        delay=1.0,
        jitter=0.1,
        seed=5,
        sleep=lambda _: None,
        on_retry=lambda attempt, exc, wait: seen.append(wait),
    )(Upstream())
    with contextlib.suppress(DownError):
        wrapped()
    rng = random.Random(5)
    _close(seen, [1.0 * (1 + rng.uniform(-0.1, 0.1)) for _ in range(2)])


def jitter_out_of_range_is_rejected() -> None:
    for bad in (1.5, -0.1):
        try:
            retry(jitter=bad)
        except ValueError:
            continue
        raise AssertionError(f"jitter={bad} was accepted")


def policy_supplies_the_published_settings() -> None:
    upstream = Upstream()
    waits = _waits(upstream, policy="billing-api")
    assert upstream.calls == 4, upstream.calls
    _close(waits, [1.2, 3.0, 7.5])
    upstream = Upstream()
    waits = _waits(upstream, policy="inventory-sync")
    assert upstream.calls == 7, upstream.calls
    _close(waits, [0.35, 0.595, 1.0115, 1.71955, 2.923235, 4.9694995])


def policy_with_a_cap_and_many_attempts() -> None:
    upstream = Upstream()
    waits = _waits(upstream, policy="email-relay")
    assert upstream.calls == 9, upstream.calls
    _close(waits, [0.05, 0.065, 0.0845, 0.10985, 0.142805, 0.1856465, 0.2, 0.2])


def explicit_arguments_beat_the_policy() -> None:
    upstream = Upstream()
    waits = _waits(upstream, policy="billing-api", max_attempts=2)
    assert upstream.calls == 2, upstream.calls
    _close(waits, [1.2])
    _close(_waits(policy="billing-api", max_attempts=3, delay=0.5), [0.5, 1.25])
    _close(_waits(policy="billing-api", max_attempts=4, backoff=1.0, max_delay=1.0), [1.0] * 3)


def unknown_policy_raises_policy_error() -> None:
    assert issubclass(retrykit.PolicyError, ValueError)
    try:
        retry(policy="no-such-policy")
    except retrykit.PolicyError as exc:
        assert "no-such-policy" in str(exc), str(exc)
        return
    raise AssertionError("an unknown policy name was accepted")


def default_is_three_attempts_with_a_fixed_delay() -> None:
    upstream = Upstream()
    waits = _waits(upstream)
    assert upstream.calls == 3 and waits == [0.5, 0.5], (upstream.calls, waits)
    upstream = Upstream()
    assert _waits(upstream, delay=0.2) == [0.2, 0.2] and upstream.calls == 3
    upstream = Upstream(failures=2, result="fine")
    assert retry(sleep=lambda _: None)(upstream)() == "fine" and upstream.calls == 3


def only_listed_exceptions_are_retried() -> None:
    upstream = Upstream()
    sleeps: list[float] = []
    try:
        retry(exceptions=(KeyError,), sleep=sleeps.append)(upstream)()
    except DownError:
        pass
    else:
        raise AssertionError("an unlisted exception was swallowed")
    assert upstream.calls == 1 and sleeps == []
    upstream = Upstream(failures=1, result="again")
    assert retry(exceptions=(DownError,), sleep=lambda _: None)(upstream)() == "again"


def on_retry_and_log_retry_still_work() -> None:
    seen: list[tuple[int, str, float]] = []
    upstream = Upstream()
    wrapped = retry(
        delay=0.3,
        sleep=lambda _: None,
        on_retry=lambda attempt, exc, wait: seen.append((attempt, str(exc), wait)),
    )(upstream)
    with contextlib.suppress(DownError):
        wrapped()
    assert seen == [(1, "down 1", 0.3), (2, "down 2", 0.3)], seen
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("hidden.retry")
    logger.addHandler(Capture())
    logger.propagate = False
    hook = retrykit.log_retry(logger)
    hook(2, DownError("x"), 0.5)
    assert records == ["attempt 2 failed (DownError: x); retrying in 0.50 s"], records


def last_exception_and_metadata_unchanged() -> None:
    upstream = Upstream()
    try:
        retry(sleep=lambda _: None)(upstream)()
    except DownError as exc:
        assert exc is upstream.errors[-1] and str(exc) == "down 3"
    else:
        raise AssertionError("no exception")

    @retry(sleep=lambda _: None)
    def documented(a: int, b: int = 1) -> int:
        """Adds."""
        return a + b

    assert documented(2, b=3) == 5
    assert documented.__name__ == "documented" and documented.__doc__ == "Adds."
    try:
        retry(delay=-1)
    except ValueError:
        return
    raise AssertionError("a negative delay was accepted")
