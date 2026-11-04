import pytest
from throttle.livestate import LiveBucket, fetch_state, parse_state

REPLY = """# gatewayd 4.2 state
reports-web 31.5 0.8
billing-export 0.25 12.0
"""


def test_parse_state_reads_each_client() -> None:
    assert parse_state(REPLY) == [
        LiveBucket("reports-web", 31.5, 0.8),
        LiveBucket("billing-export", 0.25, 12.0),
    ]


def test_parse_state_skips_comments_and_blank_lines() -> None:
    assert parse_state("# nothing tracked\n\n") == []


def test_parse_state_rejects_a_short_line() -> None:
    with pytest.raises(ValueError, match="line 2"):
        parse_state("reports-web 31.5 0.8\nbilling-export 0.25\n")


def test_fetch_state_from_gateway_daemon() -> None:
    # Needs the gateway daemon's control socket (/run/gateway/limiter.sock), which
    # exists only on the gateway hosts.
    buckets = fetch_state()
    assert buckets, "the gateway reported no buckets"
    assert all(bucket.tokens >= 0 for bucket in buckets)
