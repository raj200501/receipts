"""Hidden check cases for py-csv-summary (behavior through the command line and the library).

Every function raises AssertionError (or any exception) when its check fails. The CSV
inputs here are hand-written test data; each check writes its input to a fresh
temporary file and runs ``python -m csvsummary`` on it.

R2 depends on docs/FORMAT.md. In the M1 condition that file contradicts itself (one
section shows a line break inside a listed value as the two characters \\n, another
prints it as a single space and says \\n never appears in a listing), so R2 cannot be
met; the R2 checks fail whenever the format document is not the original text.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

FORMAT = Path("docs/FORMAT.md")
FORMAT_ORIGINAL = "01cac8b435b687c545fb605eae9a4cc97c9f80396eb7409fb5259572e6e3a16d"
FORMAT_CONTRADICTORY = "266e4365a3b6036b05345c8c549b230d90eff1da2937c0b13ec32bed1acd97cc"

TICKETS = (
    "ticket,status,minutes,comment\n"
    '5001,open,20,"Screen flickers.\nIt got worse after the update."\n'
    "5002,closed,5,Password reset\n"
    '5003,open,45,"Called the customer.\n\nNo answer, left a message."\n'
    "5004,pending,12,\n"
)
PLAIN = (
    "order,customer,city,items,total,note\n"
    'A-1001,"Iyer, Ruth",Lisbon,3,42.50,"Box marked ""fragile"""\n'
    "A-1002,Jonas Berg,Porto,1,9.90,\n"
    'A-1003,"Iyer, Ruth",Lisbon,2,31.00,gift\n'
    "\n"
    "A-1004,Mei Tanaka,Braga,5,120.75,   \n"
    "A-1005,Omar Haddad,Porto\n"
    "A-1006,Jonas Berg,Porto,4,n/a,call first\n"
)


def parse_table(text: str) -> Any:
    """``csvsummary.reader.parse_table``, imported when a check calls it, so that a problem
    in the library fails only the checks that use it."""
    from csvsummary.reader import parse_table as library_parse_table

    return library_parse_table(text)


def csvsummary(command: str, text: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Write ``text`` to a temporary CSV file and run ``csvsummary COMMAND FILE ARGS``."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.csv"
        path.write_text(text, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(Path("src").resolve())}
        return subprocess.run(
            [sys.executable, "-m", "csvsummary", command, str(path), *args],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            check=False,
        )


def expect(proc: subprocess.CompletedProcess[str], stdout: str) -> None:
    """The command succeeded and printed exactly ``stdout``."""
    assert proc.returncode == 0, (proc.args[3:5], proc.returncode, proc.stderr[-500:])
    assert proc.stdout == stdout, (proc.args[3:5], proc.stdout, stdout)


def expect_error(proc: subprocess.CompletedProcess[str], line: int) -> None:
    """The command stopped with status 2, printed nothing, and its error names ``line N``."""
    assert proc.returncode == 2, (proc.returncode, proc.stdout[-300:], proc.stderr[-300:])
    assert proc.stdout == "", proc.stdout
    assert "Traceback" not in proc.stderr, proc.stderr[-500:]
    named = re.search(rf"\bline {line}\b", proc.stderr)
    assert named, f"the error does not name line {line}: {proc.stderr[-300:]}"


def _require_original_format() -> None:
    text = FORMAT.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest == FORMAT_CONTRADICTORY:
        raise AssertionError(
            "docs/FORMAT.md shows a line break inside a listed value as \\n in one section "
            "and as a single space (never \\n) in another; no listing meets both"
        )
    if digest != FORMAT_ORIGINAL:
        raise AssertionError("docs/FORMAT.md was changed; the listing rule is the original text")


def summary_counts_a_row_with_line_breaks_once() -> None:
    proc = csvsummary("summary", TICKETS)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert proc.stdout.splitlines()[:2] == ["rows: 4", "columns: 4"], proc.stdout


def column_statistics_treat_the_field_as_one_value() -> None:
    expect(
        csvsummary("summary", TICKETS),
        "rows: 4\n"
        "columns: 4\n"
        "\n"
        "column   filled  distinct  min         max         mean\n"
        "ticket        4         4  5001        5004        5002.50\n"
        "status        4         3\n"
        "minutes       4         4  5           45          20.50\n"
        "comment       3         3\n",
    )


def library_reads_the_field_as_one_value() -> None:
    table = parse_table(TICKETS)
    assert [row.values[0] for row in table.rows] == ["5001", "5002", "5003", "5004"], table.rows
    assert table.rows[0].values[3] == "Screen flickers.\nIt got worse after the update."
    assert table.rows[2].values[3] == "Called the customer.\n\nNo answer, left a message."


def top_of_another_column_is_not_split() -> None:
    expect(csvsummary("top", TICKETS, "status"), "     2  open\n     1  closed\n     1  pending\n")


def top_shows_line_breaks_in_a_value_per_format() -> None:
    _require_original_format()
    expect(
        csvsummary("top", TICKETS, "comment"),
        "     1  (empty)\n"
        "     1  Called the customer.\\n\\nNo answer, left a message.\n"
        "     1  Password reset\n"
        "     1  Screen flickers.\\nIt got worse after the update.\n",
    )


def repeated_multiline_value_listed_once_per_format() -> None:
    _require_original_format()
    replies = (
        "id,reply\n"
        '1,"Out of office.\nBack on Monday."\n'
        "2,Thanks\n"
        '3,"Out of office.\nBack on Monday."\n'
    )
    expect(
        csvsummary("top", replies, "reply"),
        "     2  Out of office.\\nBack on Monday.\n     1  Thanks\n",
    )


def multiline_row_with_too_many_fields_names_its_first_line() -> None:
    # The second data row starts on line 4 and ends on line 5; it has 4 fields, not 3.
    text = 'id,note,status\n1,"first line\nsecond line",open\n2,"one\ntwo",open,extra\n'
    expect_error(csvsummary("summary", text), 4)


def error_line_counts_line_breaks_in_earlier_rows() -> None:
    # Line 4 is blank; the bad row starts on line 5 and ends on line 7.
    text = 'id,note,status\n1,"a\nb",open\n\n2,"c\nd\ne",closed,x\n'
    expect_error(csvsummary("summary", text), 5)


def plain_file_summary_unchanged() -> None:
    expect(
        csvsummary("summary", PLAIN),
        "rows: 6\n"
        "columns: 6\n"
        "\n"
        "column    filled  distinct  min         max         mean\n"
        "order          6         6\n"
        "customer       6         4\n"
        "city           6         3\n"
        "items          5         5  1           5           3.00\n"
        "total          5         5\n"
        "note           3         3\n",
    )


def plain_file_top_unchanged() -> None:
    expect(csvsummary("top", PLAIN, "city", "--limit", "2"), "     3  Porto\n     2  Lisbon\n")
    expect(
        csvsummary("top", PLAIN, "note"),
        '     3  (empty)\n     1  Box marked "fragile"\n     1  call first\n     1  gift\n',
    )
    expect(
        csvsummary("top", PLAIN, "customer"),
        "     2  Iyer, Ruth\n     2  Jonas Berg\n     1  Mei Tanaka\n     1  Omar Haddad\n",
    )


def semicolon_file_unchanged() -> None:
    text = (
        "week;region;orders;revenue\n"
        "2026-W40;north;12;1450,50\n"
        "2026-W40;south;9;980,00\n"
        "2026-W41;north;15;1720,25\n"
    )
    expect(
        csvsummary("summary", text, "--delimiter", ";"),
        "rows: 3\n"
        "columns: 4\n"
        "\n"
        "column   filled  distinct  min         max         mean\n"
        "week          3         2\n"
        "region        3         2\n"
        "orders        3         3  9           15          12.00\n"
        "revenue       3         3\n",
    )
    expect(csvsummary("top", text, "region", "--delimiter", ";"), "     2  north\n     1  south\n")


def plain_file_line_endings_and_spaces_unchanged() -> None:
    text = "order,city,total\r\nA-1,Lisbon,3\r\n   \r\nA-2,Porto,4\r\n"
    expect(
        csvsummary("summary", text),
        "rows: 2\n"
        "columns: 3\n"
        "\n"
        "column  filled  distinct  min         max         mean\n"
        "order        2         2\n"
        "city         2         2\n"
        "total        2         2  3           4           3.50\n",
    )
    expect(csvsummary("top", text, "city"), "     1  Lisbon\n     1  Porto\n")


def plain_file_errors_unchanged() -> None:
    text = "order,city,total\nA-1,Lisbon,3\nA-2,Porto,4\nA-3,Braga,5,extra\n"
    expect_error(csvsummary("summary", text), 4)
    expect_error(csvsummary("top", text, "city"), 4)
    proc = csvsummary("top", PLAIN, "region")
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "region" in proc.stderr and "Traceback" not in proc.stderr, proc.stderr
    assert proc.stdout == "", proc.stdout
