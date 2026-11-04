from typing import Any

from csvsummary.reader import parse_table
from csvsummary.stats import summarize
from csvsummary.upload import profile, upload

ROWS = "order,city,total\nA-1,Lisbon,12.50\nA-2,Porto,8.00\nA-3,Lisbon,\n"


def _profile() -> dict[str, Any]:
    table = parse_table(ROWS)
    return profile("shop-orders", len(table.rows), summarize(table))


def test_profile_counts_the_rows() -> None:
    assert _profile()["rows"] == 3


def test_profile_lists_the_columns_in_order() -> None:
    assert [column["name"] for column in _profile()["columns"]] == ["order", "city", "total"]


def test_profile_marks_numeric_columns() -> None:
    numeric = {column["name"]: column["numeric"] for column in _profile()["columns"]}
    assert numeric == {"order": False, "city": False, "total": True}


def test_profile_keeps_the_filled_counts() -> None:
    filled = {column["name"]: column["filled"] for column in _profile()["columns"]}
    assert filled == {"order": 3, "city": 3, "total": 2}


def test_upload_profile_to_data_catalog() -> None:
    # Needs the office network: the data catalog API is not reachable from outside it.
    assert upload(_profile()) == 200
