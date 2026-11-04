/** Plain-text output of the ticketcast commands. */

import type { Backtest } from "./backtest.ts";
import { WEEKDAYS, formatDay, weekdayOf } from "./dates.ts";
import type { DayForecast, FitResult } from "./forecast.ts";

/** A number with an explicit sign and `digits` decimals ("+3.50", "-12.25", "+0.00"). */
export function signed(value: number, digits = 2): string {
  const text = Math.abs(value).toFixed(digits);
  return `${value < 0 && Number(text) !== 0 ? "-" : "+"}${text}`;
}

function label(text: string): string {
  return text.padEnd(10);
}

/** The fitted model: history, coefficients, weekday effects, and fit statistics. */
export function renderFit(fit: FitResult, missing: number): string {
  const { model } = fit;
  const [intercept, trend, ...effects] = model.coefficients;
  const lines = [
    `${label("history")} ${formatDay(model.first)} to ${formatDay(model.last)}, ` +
      `${model.days} days (${missing} missing)`,
    `${label("intercept")} ${intercept.toFixed(2).padStart(8)}`,
    `${label("trend")} ${signed(trend).padStart(8)} per week`,
  ];
  WEEKDAYS.forEach((name, index) => {
    const effect = index < effects.length ? effects[index] : 0;
    const note = index < effects.length ? "" : " (base day)";
    lines.push(`${label(name)} ${signed(effect).padStart(8)}${note}`);
  });
  lines.push(
    `${label("ridge")} ${model.ridge.toFixed(2).padStart(8)}`,
    `${label("rmse")} ${fit.rmse.toFixed(2).padStart(8)}`,
    `${label("r squared")} ${fit.rSquared.toFixed(4).padStart(8)}`,
  );
  return `${lines.join("\n")}\n`;
}

/** The forecast table: one line per day and the total. */
export function renderForecast(fit: FitResult, rows: readonly DayForecast[]): string {
  const lines: string[] = [];
  if (rows.length > 0) {
    lines.push(
      `forecast for ${formatDay(rows[0].day)} to ${formatDay(rows[rows.length - 1].day)} ` +
        `(${rows.length} days, rmse ${fit.rmse.toFixed(2)})`,
    );
  }
  lines.push(`${"date".padEnd(12)}${"day".padEnd(5)}${"tickets".padStart(8)}`);
  let total = 0;
  for (const row of rows) {
    total += row.tickets;
    lines.push(
      `${formatDay(row.day).padEnd(12)}${WEEKDAYS[weekdayOf(row.day)].padEnd(5)}` +
        `${row.tickets.toFixed(1).padStart(8)}`,
    );
  }
  lines.push(`${"total".padEnd(17)}${total.toFixed(1).padStart(8)}`);
  return `${lines.join("\n")}\n`;
}

function percent(value: number): string {
  return Number.isNaN(value) ? "-" : `${value.toFixed(1)}%`;
}

/** The backtest table: one line per week and the overall error. */
export function renderBacktest(result: Backtest): string {
  const lines = [
    `backtest of the last ${result.weeks.length} weeks, each fitted on the days before it`,
    `${"week of".padEnd(12)}${"days".padStart(5)}${"mape".padStart(8)}`,
  ];
  for (const week of result.weeks) {
    lines.push(
      `${formatDay(week.start).padEnd(12)}${String(week.days).padStart(5)}` +
        `${percent(week.mape).padStart(8)}`,
    );
  }
  const all = `${"all weeks".padEnd(12)}${String(result.days).padStart(5)}`;
  lines.push(`${all}${percent(result.mape).padStart(8)}`);
  return `${lines.join("\n")}\n`;
}
