import pytest
from throttle.clock import ManualClock, MonotonicClock


def test_manual_clock_starts_at_the_given_time() -> None:
    assert ManualClock().now() == 0.0
    assert ManualClock(12.5).now() == 12.5


def test_manual_clock_set_and_advance() -> None:
    clock = ManualClock()
    clock.set(3.0)
    clock.advance(1.5)
    assert clock.now() == 4.5


def test_manual_clock_never_goes_back() -> None:
    clock = ManualClock(10.0)
    with pytest.raises(ValueError, match="cannot go back"):
        clock.set(9.0)


def test_manual_clock_cannot_advance_by_a_negative_time() -> None:
    with pytest.raises(ValueError):
        ManualClock().advance(-1)


def test_monotonic_clock_does_not_go_back() -> None:
    clock = MonotonicClock()
    first = clock.now()
    assert clock.now() >= first
