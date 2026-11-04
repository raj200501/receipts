import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDay, parseDay } from "../src/dates.ts";
import { ForecastError, fitModel, forecast, predict, residualStats } from "../src/forecast.ts";
import type { DayCount } from "../src/history.ts";

// Mon to Sun; Sunday is the base day of the model.
const EFFECTS = [30, 20, 10, 5, -5, -40, 0];

/** Tickets that follow the model exactly: 100 + 7 per week + the weekday effect. */
function exactHistory(days: number, start = "2026-03-02"): DayCount[] {
  const first = parseDay(start) as number;
  const rows: DayCount[] = [];
  for (let i = 0; i < days; i++) {
    rows.push({ day: first + i, tickets: 100 + i + EFFECTS[i % 7] });
  }
  return rows;
}

function close(actual: number, expected: number, what: string): void {
  assert.ok(Math.abs(actual - expected) < 1e-6, `${what}: got ${actual}, expected ${expected}`);
}

test("fitModel recovers an exact trend and weekday effects", () => {
  const { model, rmse, rSquared } = fitModel(exactHistory(28));
  const expected = [100, 7, 30, 20, 10, 5, -5, -40];
  model.coefficients.forEach((value, i) => close(value, expected[i], `coefficient ${i}`));
  close(rmse, 0, "rmse");
  close(rSquared, 1, "r squared");
  assert.equal(model.days, 28);
  assert.equal(formatDay(model.last), "2026-03-29");
});

test("a ridge penalty shrinks the weekday effects", () => {
  const plain = fitModel(exactHistory(28)).model.coefficients;
  const ridge = fitModel(exactHistory(28), { ridge: 50 }).model.coefficients;
  for (let i = 2; i < 8; i++) {
    assert.ok(Math.abs(ridge[i]) < Math.abs(plain[i]), `effect ${i}`);
  }
});

test("a history shorter than two weeks is rejected", () => {
  assert.throws(() => fitModel(exactHistory(13)), {
    name: "ForecastError",
    message: "the history needs at least 14 days, got 13",
  });
});

test("a history without a single Monday cannot be fitted", () => {
  const noMondays = exactHistory(28).filter((_, i) => i % 7 !== 0);
  assert.throws(() => fitModel(noMondays), {
    name: "ForecastError",
    message: "cannot fit the history: matrix is singular (every weekday needs at least one day)",
  });
});

test("a negative ridge penalty is rejected", () => {
  assert.throws(() => fitModel(exactHistory(28), { ridge: -1 }), ForecastError);
});

test("forecast starts the day after the history and follows the model", () => {
  const { model } = fitModel(exactHistory(28));
  const rows = forecast(model, 3);
  assert.deepEqual(
    rows.map((row) => formatDay(row.day)),
    ["2026-03-30", "2026-03-31", "2026-04-01"],
  );
  close(rows[0].tickets, 100 + 28 + 30, "Monday after the history");
  close(rows[2].tickets, 100 + 30 + 10, "Wednesday after the history");
});

test("predictions never go below zero", () => {
  const falling = exactHistory(21).map((row, i) => ({ day: row.day, tickets: 300 - 10 * i }));
  const { model } = fitModel(falling);
  assert.equal(predict(model, model.last + 60), 0);
});

test("residualStats measures the error of fitted values", () => {
  const { rmse, rSquared } = residualStats([10, 20, 30, 40], [12, 18, 30, 40]);
  close(rmse, Math.sqrt(2), "rmse");
  close(rSquared, 1 - 8 / 500, "r squared");
});
