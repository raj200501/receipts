import logging

import pytest
from retrykit import log_retry, retry


def test_log_retry_logs_a_warning_per_failed_attempt(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("retrykit.test")
    calls = {"n": 0}

    @retry(delay=0.25, sleep=lambda _: None, on_retry=log_retry(logger))
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("slow upstream")
        return "ok"

    with caplog.at_level(logging.WARNING, logger="retrykit.test"):
        assert flaky() == "ok"
    assert [record.getMessage() for record in caplog.records] == [
        "attempt 1 failed (TimeoutError: slow upstream); retrying in 0.25 s",
        "attempt 2 failed (TimeoutError: slow upstream); retrying in 0.25 s",
    ]


def test_log_retry_level_can_be_changed(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("retrykit.level")
    hook = log_retry(logger, level=logging.INFO)
    with caplog.at_level(logging.INFO, logger="retrykit.level"):
        hook(1, ValueError("x"), 1.0)
    assert caplog.records[0].levelno == logging.INFO
