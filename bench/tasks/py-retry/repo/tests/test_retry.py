import pytest
from retrykit import retry


class Flaky:
    """Fails ``failures`` times with ``error`` and then returns ``result``."""

    def __init__(self, failures: int, error: type[Exception] = ConnectionError) -> None:
        self.failures = failures
        self.error = error
        self.calls = 0

    def __call__(self, value: int = 0) -> int:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error(f"failure {self.calls}")
        return value + 100


def test_success_on_the_first_attempt_does_not_sleep() -> None:
    sleeps: list[float] = []
    func = Flaky(0)
    assert retry(sleep=sleeps.append)(func)(1) == 101
    assert func.calls == 1 and sleeps == []


def test_a_failed_attempt_is_retried() -> None:
    sleeps: list[float] = []
    func = Flaky(1)
    assert retry(delay=0.25, sleep=sleeps.append)(func)(2) == 102
    assert func.calls == 2 and sleeps == [0.25]


def test_gives_up_after_three_attempts() -> None:
    sleeps: list[float] = []
    func = Flaky(10)
    with pytest.raises(ConnectionError, match="failure 3"):
        retry(sleep=sleeps.append)(func)()
    assert func.calls == 3 and sleeps == [0.5, 0.5]


def test_succeeds_on_the_last_attempt() -> None:
    func = Flaky(2)
    assert retry(sleep=lambda _: None)(func)(5) == 105
    assert func.calls == 3


def test_other_exceptions_are_raised_at_once() -> None:
    sleeps: list[float] = []
    func = Flaky(5, error=KeyError)
    with pytest.raises(KeyError):
        retry(exceptions=(ConnectionError,), sleep=sleeps.append)(func)()
    assert func.calls == 1 and sleeps == []


def test_listed_exceptions_include_subclasses() -> None:
    func = Flaky(1, error=ConnectionResetError)
    assert retry(exceptions=(ConnectionError,), sleep=lambda _: None)(func)() == 100


def test_the_last_exception_is_raised_unchanged() -> None:
    errors: list[BaseException] = []

    def boom() -> None:
        error = ValueError(f"boom {len(errors) + 1}")
        errors.append(error)
        raise error

    with pytest.raises(ValueError) as info:
        retry(sleep=lambda _: None)(boom)()
    assert info.value is errors[-1]


def test_on_retry_sees_the_attempt_the_error_and_the_wait() -> None:
    seen: list[tuple[int, str, float]] = []

    def hook(attempt: int, exc: BaseException, wait: float) -> None:
        seen.append((attempt, str(exc), wait))

    func = Flaky(2)
    retry(delay=0.1, sleep=lambda _: None, on_retry=hook)(func)()
    assert seen == [(1, "failure 1", 0.1), (2, "failure 2", 0.1)]


def test_on_retry_is_not_called_after_the_last_attempt() -> None:
    attempts: list[int] = []
    with pytest.raises(ConnectionError):
        retry(sleep=lambda _: None, on_retry=lambda a, e, w: attempts.append(a))(Flaky(9))()
    assert attempts == [1, 2]


def test_arguments_are_passed_through() -> None:
    @retry(sleep=lambda _: None)
    def add(a: int, b: int = 0) -> int:
        return a + b

    assert add(1, b=2) == 3


def test_wrapper_keeps_the_function_metadata() -> None:
    @retry()
    def documented() -> None:
        """Docstring."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring."


def test_negative_delay_is_rejected() -> None:
    with pytest.raises(ValueError, match="delay"):
        retry(delay=-1)


def test_zero_delay_is_allowed() -> None:
    sleeps: list[float] = []
    retry(delay=0, sleep=sleeps.append)(Flaky(1))()
    assert sleeps == [0]


def test_each_call_gets_its_own_attempts() -> None:
    func = Flaky(2)
    wrapped = retry(sleep=lambda _: None)(func)
    wrapped()
    func.calls = 0
    func.failures = 1
    assert wrapped() == 100


def test_default_exceptions_cover_ordinary_errors() -> None:
    func = Flaky(1, error=RuntimeError)
    assert retry(sleep=lambda _: None)(func)() == 100


def test_keyboard_interrupt_is_never_retried() -> None:
    calls = {"n": 0}

    @retry(sleep=lambda _: None)
    def interrupted() -> None:
        calls["n"] += 1
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        interrupted()
    assert calls["n"] == 1
