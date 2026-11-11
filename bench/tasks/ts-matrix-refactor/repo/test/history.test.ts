import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDay } from "../src/dates.ts";
import { HistoryError, missingDays, parseHistory } from "../src/history.ts";

test("reads one row per day", () => {
  const rows = parseHistory("date,tickets\n2026-07-06,152\n2026-07-07,146\n");
  assert.deepEqual(
    rows.map((row) => [formatDay(row.day), row.tickets]),
    [
      ["2026-07-06", 152],
      ["2026-07-07", 146],
    ],
  );
});

test("skips blank lines and reads CRLF line endings", () => {
  const rows = parseHistory("date,tickets\r\n\r\n2026-07-06,152\r\n\r\n2026-07-07,0\r\n");
  assert.equal(rows.length, 2);
  assert.equal(rows[1].tickets, 0);
});

test("a file without the header is rejected on line 1", () => {
  assert.throws(() => parseHistory("day,count\n2026-07-06,152\n"), {
    name: "HistoryError",
    message: 'line 1: expected the header "date,tickets"',
  });
  assert.throws(() => parseHistory(""), HistoryError);
});

test("a date that does not exist names its line", () => {
  assert.throws(() => parseHistory("date,tickets\n2026-07-06,152\n2026-06-31,140\n"), {
    message: 'line 3: not a YYYY-MM-DD date: "2026-06-31"',
  });
});

test("tickets must be whole numbers of at least 0", () => {
  for (const value of ["12.5", "-3", "", "many"]) {
    assert.throws(() => parseHistory(`date,tickets\n2026-07-06,${value}\n`), {
      message: `line 2: tickets must be a whole number of at least 0, got ${JSON.stringify(value)}`,
    });
  }
});

test("dates must increase", () => {
  assert.throws(() => parseHistory("date,tickets\n2026-07-07,152\n2026-07-06,140\n"), {
    message: "line 3: dates must increase, got 2026-07-06 after 2026-07-07",
  });
  assert.throws(() => parseHistory("date,tickets\n2026-07-07,1,2\n"), {
    message: "line 2: expected 2 fields, got 3",
  });
});

test("counts the days missing between the first and the last day", () => {
  const rows = parseHistory("date,tickets\n2026-07-06,152\n2026-07-08,140\n2026-07-11,61\n");
  assert.equal(missingDays(rows), 3);
  assert.equal(missingDays([]), 0);
});
