/**
 * Rolling-origin backtest: for each of the last weeks of a history, fit the model on the
 * days before that week and compare its predictions with the tickets that came in.
 */

import { mondayOf } from "./dates.ts";
import {
  ForecastError,
  MIN_HISTORY_DAYS,
  designRow,
  fitModel,
  multiplyVector,
} from "./forecast.ts";
import type { FitOptions } from "./forecast.ts";
import type { DayCount } from "./history.ts";

/** The error of one backtest week. */
export interface BacktestWeek {
  /** The Monday the week starts on. */
  start: number;
  /** Days compared: days of the week with a row and at least one ticket. */
  days: number;
  /** Mean absolute percentage error over those days, in percent (NaN without days). */
  mape: number;
}

/** A whole backtest. */
export interface Backtest {
  weeks: BacktestWeek[];
  days: number;
  /** Mean absolute percentage error over every compared day, in percent. */
  mape: number;
}

/** Sum of the absolute percentage errors (as fractions) of one week's predictions. */
function weekError(week: readonly DayCount[], predicted: readonly number[]): number {
  let error = 0;
  week.forEach((row, i) => {
    error += Math.abs(row.tickets - Math.max(0, predicted[i])) / row.tickets;
  });
  return error;
}

/** Backtest the last `weeks` calendar weeks (Monday to Sunday) of a history. */
export function backtest(
  history: readonly DayCount[],
  weeks: number,
  options: FitOptions = {},
): Backtest {
  if (history.length === 0) {
    throw new ForecastError("the history is empty");
  }
  const lastMonday = mondayOf(history[history.length - 1].day);
  const results: BacktestWeek[] = [];
  let totalError = 0;
  let totalDays = 0;
  for (let index = weeks - 1; index >= 0; index--) {
    const start = lastMonday - 7 * index;
    const train = history.filter((row) => row.day < start);
    if (train.length < MIN_HISTORY_DAYS) {
      throw new ForecastError(
        `not enough history before the backtest week ${weeks - index} ` +
          `(needs ${MIN_HISTORY_DAYS} days)`,
      );
    }
    const { model } = fitModel(train, options);
    const week = history.filter(
      (row) => row.day >= start && row.day < start + 7 && row.tickets > 0,
    );
    const rows = week.map((row) => designRow(model.first, row.day));
    const error = weekError(week, multiplyVector(rows, model.coefficients));
    const mape = week.length > 0 ? (100 * error) / week.length : Number.NaN;
    results.push({ start, days: week.length, mape });
    totalError += error;
    totalDays += week.length;
  }
  return {
    weeks: results,
    days: totalDays,
    mape: totalDays > 0 ? (100 * totalError) / totalDays : Number.NaN,
  };
}
