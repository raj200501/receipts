import pytest
from logsift.entries import LEVELS, severity


def test_levels_run_from_least_to_most_severe() -> None:
    assert LEVELS == ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")


@pytest.mark.parametrize(("level", "rank"), [("DEBUG", 0), ("WARN", 2), ("FATAL", 4)])
def test_severity_is_the_position_in_levels(level: str, rank: int) -> None:
    assert severity(level) == rank


def test_severity_rejects_unknown_levels() -> None:
    with pytest.raises(ValueError):
        severity("NOTICE")
