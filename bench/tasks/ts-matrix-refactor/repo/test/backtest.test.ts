import assert from "node:assert/strict";
import { test } from "node:test";
import { backtest } from "../src/backtest.ts";
import { formatDay, parseDay } from "../src/dates.ts";
import type { DayCount } from "../src/history.ts";

const EFFECTS = [30, 20, 10, 5, -5, -40, 0];

function exactHistory(days: number, start = "2026-03-02"): DayCount[] {
  const first = parseDay(start) as number;
  return Array.from({ length: days }, (_, i) => ({
    day: first + i,
    tickets: 100 + i + EFFECTS[i % 7],
  }));
}

test("a history that follows the model backtests without error", () => {
  const result = backtest(exactHistory(42), 3);
  assert.equal(result.weeks.length, 3);
  assert.equal(result.days, 21);
  assert.ok(result.mape < 1e-6, `mape ${result.mape}`);
});

test("backtest weeks run Monday to Sunday and end with the last week", () => {
  // The history ends on a Wednesday, so the last backtest week has three days.
  const result = backtest(exactHistory(38), 2);
  assert.deepEqual(
    result.weeks.map((week) => [formatDay(week.start), week.days]),
    [
      ["2026-03-30", 7],
      ["2026-04-06", 3],
    ],
  );
});

test("too little history before the first backtest week is an error", () => {
  assert.throws(() => backtest(exactHistory(28), 3), {
    name: "ForecastError",
    message: "not enough history before the backtest week 1 (needs 14 days)",
  });
});
