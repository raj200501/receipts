import pytest
from tinycache import memoize


def test_results_are_cached() -> None:
    calls: list[int] = []

    @memoize(maxsize=4)
    def square(n: int) -> int:
        calls.append(n)
        return n * n

    assert [square(3), square(3), square(4)] == [9, 9, 16]
    assert calls == [3, 4]


def test_keyword_calls_are_cached_separately_from_positional() -> None:
    calls: list[object] = []

    @memoize()
    def echo(value: int) -> int:
        calls.append(value)
        return value

    echo(1)
    echo(value=1)
    echo(value=1)
    assert len(calls) == 2


def test_none_results_are_cached() -> None:
    calls: list[int] = []

    @memoize()
    def nothing(n: int) -> None:
        calls.append(n)

    nothing(1)
    nothing(1)
    assert calls == [1]


def test_oldest_result_is_dropped_at_maxsize() -> None:
    calls: list[int] = []

    @memoize(maxsize=2)
    def ident(n: int) -> int:
        calls.append(n)
        return n

    for n in (1, 2, 3, 1):
        ident(n)
    assert calls == [1, 2, 3, 1]


def test_cache_is_exposed() -> None:
    @memoize(maxsize=2)
    def ident(n: int) -> int:
        return n

    ident(1)
    assert len(ident.cache) == 1  # type: ignore[attr-defined]
    ident.cache_clear()  # type: ignore[attr-defined]
    assert len(ident.cache) == 0  # type: ignore[attr-defined]


def test_wrapper_keeps_the_function_metadata() -> None:
    @memoize()
    def documented(n: int) -> int:
        """Docstring."""
        return n

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring."


def test_exceptions_are_not_cached() -> None:
    calls: list[int] = []

    @memoize()
    def flaky(n: int) -> int:
        calls.append(n)
        if len(calls) == 1:
            raise RuntimeError("first call fails")
        return n

    with pytest.raises(RuntimeError):
        flaky(1)
    assert flaky(1) == 1
    assert calls == [1, 1]
