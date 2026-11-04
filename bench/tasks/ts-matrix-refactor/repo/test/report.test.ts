import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDay } from "../src/dates.ts";
import type { FitResult } from "../src/forecast.ts";
import { renderBacktest, renderFit, renderForecast, signed } from "../src/report.ts";

const MONDAY = parseDay("2026-07-06") as number;

const FIT: FitResult = {
  model: {
    first: MONDAY,
    last: MONDAY + 27,
    days: 27,
    ridge: 0,
    coefficients: [121.012, 2.3, 36.4, 26.8, 16.5, 14.3, 6.7, -50.25],
  },
  rmse: 3.861,
  rSquared: 0.97934,
};

test("signed numbers keep their sign and never print -0.00", () => {
  assert.equal(signed(3.5), "+3.50");
  assert.equal(signed(-12.254), "-12.25");
  assert.equal(signed(-0.001), "+0.00");
  assert.equal(signed(0.26, 1), "+0.3");
});

test("renderFit lists every weekday with Sunday as the base day", () => {
  assert.equal(
    renderFit(FIT, 1),
    [
      "history    2026-07-06 to 2026-08-02, 27 days (1 missing)",
      "intercept    121.01",
      "trend         +2.30 per week",
      "Mon          +36.40",
      "Tue          +26.80",
      "Wed          +16.50",
      "Thu          +14.30",
      "Fri           +6.70",
      "Sat          -50.25",
      "Sun           +0.00 (base day)",
      "ridge          0.00",
      "rmse           3.86",
      "r squared    0.9793",
      "",
    ].join("\n"),
  );
});

test("renderForecast prints one line per day and the total", () => {
  const rows = [
    { day: MONDAY + 28, tickets: 185.14 },
    { day: MONDAY + 29, tickets: 175.82 },
  ];
  assert.equal(
    renderForecast(FIT, rows),
    [
      "forecast for 2026-08-03 to 2026-08-04 (2 days, rmse 3.86)",
      "date        day   tickets",
      "2026-08-03  Mon     185.1",
      "2026-08-04  Tue     175.8",
      "total               361.0",
      "",
    ].join("\n"),
  );
});

test("renderBacktest prints a dash for a week without data", () => {
  const text = renderBacktest({
    weeks: [
      { start: MONDAY, days: 7, mape: 2.04 },
      { start: MONDAY + 7, days: 0, mape: Number.NaN },
    ],
    days: 7,
    mape: 2.04,
  });
  assert.equal(
    text,
    [
      "backtest of the last 2 weeks, each fitted on the days before it",
      "week of      days    mape",
      "2026-07-06      7    2.0%",
      "2026-07-13      0       -",
      "all weeks       7    2.0%",
      "",
    ].join("\n"),
  );
});
