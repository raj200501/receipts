from pathlib import Path

import pytest
from csvsummary.reader import Row, TableError, parse_table, read_table

ORDERS = "order,customer,total\nA-1,Ruth Iyer,12.50\nA-2,Jonas Berg,8.00\n"


def test_header_and_rows_are_read() -> None:
    table = parse_table(ORDERS)
    assert table.header == ("order", "customer", "total")
    assert table.rows == (
        Row(2, ("A-1", "Ruth Iyer", "12.50")),
        Row(3, ("A-2", "Jonas Berg", "8.00")),
    )


def test_header_names_are_stripped() -> None:
    assert parse_table(" order , total \nA-1,3\n").header == ("order", "total")


def test_blank_lines_are_skipped_and_line_numbers_kept() -> None:
    table = parse_table("\norder,total\n\nA-1,3\n   \nA-2,4\n")
    assert [row.line for row in table.rows] == [4, 6]


def test_short_rows_are_padded_with_empty_values() -> None:
    (row,) = parse_table("order,customer,total\nA-1,Ruth Iyer\n").rows
    assert row.values == ("A-1", "Ruth Iyer", "")


def test_row_of_empty_fields_is_a_row() -> None:
    (row,) = parse_table("order,total\n,\n").rows
    assert row.values == ("", "")


def test_too_many_fields_names_the_line() -> None:
    with pytest.raises(TableError, match="line 3: expected at most 3 fields, got 4"):
        parse_table(ORDERS.replace("A-2,Jonas Berg,8.00", "A-2,Jonas Berg,8.00,x"))


def test_quoted_field_may_contain_the_delimiter() -> None:
    (row,) = parse_table('order,customer\nA-1,"Iyer, Ruth"\n').rows
    assert row.values == ("A-1", "Iyer, Ruth")


def test_doubled_quotes_inside_a_quoted_field() -> None:
    (row,) = parse_table('order,note\nA-1,"Box marked ""fragile"""\n').rows
    assert row.values == ("A-1", 'Box marked "fragile"')


def test_another_delimiter() -> None:
    table = parse_table("order;total\nA-1;12,50\n", delimiter=";")
    assert table.rows[0].values == ("A-1", "12,50")


def test_delimiter_must_be_one_character() -> None:
    with pytest.raises(ValueError, match="one character"):
        parse_table(ORDERS, delimiter=";;")


def test_empty_column_name_is_rejected() -> None:
    with pytest.raises(TableError, match="line 1: the header row has an empty column name"):
        parse_table("order,,total\nA-1,x,3\n")


def test_duplicate_column_name_is_rejected() -> None:
    with pytest.raises(TableError, match="names the column 'total' twice"):
        parse_table("order,total,total\nA-1,3,4\n")


def test_empty_file_is_rejected() -> None:
    with pytest.raises(TableError, match="empty"):
        parse_table("\n\n")


def test_column_returns_values_in_row_order() -> None:
    assert parse_table(ORDERS).column("customer") == ["Ruth Iyer", "Jonas Berg"]


def test_unknown_column_lists_the_columns() -> None:
    with pytest.raises(KeyError, match="columns: order, customer, total"):
        parse_table(ORDERS).column("city")


def test_read_table_ignores_a_byte_order_mark(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.write_text("\ufeff" + ORDERS, encoding="utf-8")
    assert read_table(path).header[0] == "order"
