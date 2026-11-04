import pytest
import retrykit
from retrykit import defaults, retry


def test_default_delay_is_half_a_second() -> None:
    assert defaults.DEFAULT_DELAY == 0.5


def test_default_attempts_are_three() -> None:
    assert defaults.MAX_TRIES == 3


def test_public_names_are_exported() -> None:
    assert set(retrykit.__all__) == {"PolicyError", "log_retry", "retry"}


def test_version_is_a_dotted_string() -> None:
    assert retrykit.__version__.count(".") == 2


def test_retry_takes_keyword_arguments_only() -> None:
    with pytest.raises(TypeError):
        retry(0.5)  # type: ignore[misc]
