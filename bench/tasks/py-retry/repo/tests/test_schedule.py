import pytest
from retrykit.schedule import fixed_delay


def test_fixed_delay_is_the_base() -> None:
    assert [fixed_delay(0.5, n) for n in (1, 2, 3, 10)] == [0.5, 0.5, 0.5, 0.5]


def test_attempt_numbers_start_at_one() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        fixed_delay(0.5, 0)


def test_zero_base_gives_zero() -> None:
    assert fixed_delay(0.0, 2) == 0.0
