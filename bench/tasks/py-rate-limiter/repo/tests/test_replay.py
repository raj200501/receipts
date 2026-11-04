import pytest
from throttle.policy import Limit, Policy
from throttle.replay import LogError, parse_log, render_report, replay

POLICY = Policy(default=Limit(burst=2, per_minute=60), clients={})
HEADER = "time,client,method,path\n"


def _log(*rows: str) -> str:
    return HEADER + "".join(f"{row}\n" for row in rows)


def test_parse_log_reads_requests() -> None:
    (request,) = parse_log(_log("2026-10-28T14:00:00.250Z,reports-web,GET,/v1/reports"))
    assert (request.line, request.client, request.method, request.path) == (
        2,
        "reports-web",
        "GET",
        "/v1/reports",
    )
    assert request.stamp == "2026-10-28T14:00:00.250Z"
    assert request.when.microsecond == 250_000


def test_blank_lines_are_skipped() -> None:
    text = HEADER + "\n2026-10-28T14:00:00Z,a,GET,/\n\n2026-10-28T14:00:01Z,b,GET,/\n"
    assert [request.line for request in parse_log(text)] == [3, 5]


def test_header_is_required() -> None:
    with pytest.raises(LogError, match="line 1: expected the header"):
        parse_log("2026-10-28T14:00:00Z,a,GET,/\n")


def test_invalid_time_names_the_line() -> None:
    with pytest.raises(LogError, match="line 3: invalid time"):
        parse_log(_log("2026-10-28T14:00:00Z,a,GET,/", "yesterday,a,GET,/"))


def test_time_without_an_offset_is_rejected() -> None:
    with pytest.raises(LogError, match="line 2: invalid time"):
        parse_log(_log("2026-10-28T14:00:00,a,GET,/"))


def test_time_going_backwards_names_the_line() -> None:
    with pytest.raises(LogError, match=r"line 3: time .* goes backwards"):
        parse_log(_log("2026-10-28T14:00:05Z,a,GET,/", "2026-10-28T14:00:04Z,a,GET,/"))


def test_wrong_number_of_fields() -> None:
    with pytest.raises(LogError, match="line 2: expected 4 fields, got 3"):
        parse_log(_log("2026-10-28T14:00:00Z,a,GET"))


def test_missing_client() -> None:
    with pytest.raises(LogError, match="line 2: missing client"):
        parse_log(_log("2026-10-28T14:00:00Z,,GET,/"))


def test_replay_counts_allowed_and_rejected() -> None:
    stamps = ("00.000", "00.100", "00.200", "01.500")
    requests = parse_log(_log(*(f"2026-10-28T14:00:{s}Z,a,GET,/" for s in stamps)))
    totals = replay(requests, POLICY).totals["a"]
    assert (totals.allowed, totals.rejected) == (3, 1)


def test_replay_keeps_clients_apart() -> None:
    requests = parse_log(
        _log(*(f"2026-10-28T14:00:00Z,{client},GET,/" for client in ("a", "a", "a", "b")))
    )
    result = replay(requests, POLICY)
    assert {name: (t.allowed, t.rejected) for name, t in result.totals.items()} == {
        "a": (2, 1),
        "b": (1, 0),
    }


def test_empty_log_replays_to_nothing() -> None:
    assert replay(parse_log(HEADER), POLICY).totals == {}


def test_report_layout() -> None:
    requests = parse_log(_log(*("2026-10-28T14:00:00Z,reports-web,GET,/" for _ in range(3))))
    assert render_report(replay(requests, POLICY)) == (
        "client       allowed  rejected\n"
        "reports-web        2         1\n"
        "total              2         1\n"
    )


def test_report_lists_rejected_requests() -> None:
    requests = parse_log(_log(*("2026-10-28T14:00:00Z,a,GET,/v1" for _ in range(3))))
    report = render_report(replay(requests, POLICY), rejected=True)
    assert report.splitlines()[-2:] == [
        "rejected requests:",
        "2026-10-28T14:00:00Z  a  GET /v1  retry after 1 s",
    ]


def test_report_without_rejections() -> None:
    requests = parse_log(_log("2026-10-28T14:00:00Z,a,GET,/"))
    assert render_report(replay(requests, POLICY), rejected=True).endswith(
        "\nrejected requests: none\n"
    )
