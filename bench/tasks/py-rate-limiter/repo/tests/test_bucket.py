import pytest
from throttle.bucket import TokenBucket
from throttle.clock import ManualClock


def test_new_bucket_is_full() -> None:
    assert TokenBucket(5, 1.0, ManualClock()).tokens() == 5


def test_take_until_empty() -> None:
    bucket = TokenBucket(3, 1.0, ManualClock())
    assert [bucket.try_take() for _ in range(4)] == [True, True, True, False]


def test_refills_at_its_rate() -> None:
    clock = ManualClock()
    bucket = TokenBucket(4, 2.0, clock, tokens=0)
    clock.advance(1.25)
    assert bucket.tokens() == 2.5


def test_never_holds_more_than_its_capacity() -> None:
    clock = ManualClock()
    bucket = TokenBucket(4, 2.0, clock, tokens=1)
    clock.advance(3600)
    assert bucket.tokens() == 4


def test_can_start_partly_full() -> None:
    bucket = TokenBucket(10, 1.0, ManualClock(), tokens=2.5)
    assert [bucket.try_take() for _ in range(3)] == [True, True, False]


def test_seconds_until_token() -> None:
    bucket = TokenBucket(2, 0.5, ManualClock(), tokens=0)
    assert bucket.seconds_until_token() == 2.0


def test_seconds_until_token_is_zero_while_one_is_left() -> None:
    assert TokenBucket(2, 0.5, ManualClock(), tokens=1).seconds_until_token() == 0.0


@pytest.mark.parametrize(("capacity", "rate"), [(0, 1.0), (5, 0.0), (-1, 1.0)])
def test_capacity_and_rate_must_be_positive(capacity: float, rate: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        TokenBucket(capacity, rate, ManualClock())
