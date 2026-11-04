import random

import pytest
from retrykit import PolicyError, retry


def always_fails() -> None:
    raise ConnectionError("down")


def sleeps_of(**options: object) -> list[float]:
    sleeps: list[float] = []
    with pytest.raises(ConnectionError):
        retry(sleep=sleeps.append, **options)(always_fails)()  # type: ignore[arg-type]
    return sleeps


def test_max_attempts_limits_the_calls() -> None:
    calls: list[int] = []

    def failing() -> None:
        calls.append(1)
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        retry(max_attempts=5, sleep=lambda _: None)(failing)()
    assert len(calls) == 5


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        retry(max_attempts=0)


def test_backoff_grows_the_delay() -> None:
    assert sleeps_of(max_attempts=5, delay=0.5, backoff=2) == [0.5, 1.0, 2.0, 4.0]


def test_max_delay_caps_the_wait() -> None:
    assert sleeps_of(max_attempts=5, delay=0.5, backoff=2, max_delay=1.5) == [0.5, 1.0, 1.5, 1.5]


def test_jitter_is_reproducible_with_a_seed() -> None:
    first = sleeps_of(max_attempts=4, delay=1.0, jitter=0.5, seed=3)
    assert first == sleeps_of(max_attempts=4, delay=1.0, jitter=0.5, seed=3)
    rng = random.Random(3)
    assert first == pytest.approx([1.0 * (1 + rng.uniform(-0.5, 0.5)) for _ in range(3)])


def test_jitter_must_be_a_fraction() -> None:
    with pytest.raises(ValueError, match="jitter"):
        retry(jitter=1.5)


def test_policy_supplies_the_settings() -> None:
    sleeps = sleeps_of(policy="billing-api")
    assert sleeps == pytest.approx([1.2, 3.0, 7.5])


def test_explicit_arguments_beat_the_policy() -> None:
    assert sleeps_of(policy="billing-api", max_attempts=2) == pytest.approx([1.2])


def test_unknown_policy_is_an_error() -> None:
    with pytest.raises(PolicyError, match="unknown retry policy 'nope'"):
        retry(policy="nope")
