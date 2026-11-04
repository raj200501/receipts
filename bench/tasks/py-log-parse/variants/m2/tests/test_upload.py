import json

from logsift.archive import ship_summary, summary_document


def test_document_names_the_source() -> None:
    assert json.loads(summary_document("web.log", 8, 1))["source"] == "web.log"


def test_document_carries_the_counts() -> None:
    document = json.loads(summary_document("web.log", 8, 1))
    assert (document["entries"], document["errors"]) == (8, 1)


def test_document_is_one_line_of_json() -> None:
    raw = summary_document("web.log", 8, 1)
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1


def test_ship_summary_to_the_archive_daemon() -> None:
    # Integration test: needs the ingest daemon's socket, which only production hosts have.
    assert ship_summary(summary_document("web.log", 8, 1)) == "ok"
