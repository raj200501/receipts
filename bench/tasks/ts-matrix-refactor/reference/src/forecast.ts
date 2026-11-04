/**
 * The ticket volume model.
 *
 * The model is a straight-line trend plus one effect per weekday:
 *
 *     tickets = intercept + trend * weeks + effect[weekday]
 *
 * where `weeks` counts weeks since the first day of the history and Sunday is the base
 * day (its effect is 0). It is fitted by least squares through the normal equations
 * (X^T X + P) b = X^T y, where the ridge penalty P adds `ridge` to the diagonal for
 * every coefficient except the intercept. The matrix code is in matrix.ts.
 */

import { weekdayOf } from "./dates.ts";
import type { DayCount } from "./history.ts";
import {
  SingularMatrixError,
  identity,
  multiply,
  multiplyVector,
  solve,
  transpose,
} from "./matrix.ts";

/** Coefficients: intercept, trend per week, then the effects of Monday to Saturday. */
export const COEFFICIENTS = 8;

/** The fewest days of history a fit accepts. */
export const MIN_HISTORY_DAYS = 14;

/** A history the model cannot be fitted to, or options it cannot use. */
export class ForecastError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ForecastError";
  }
}

/** Options of fitModel. */
export interface FitOptions {
  /** Ridge penalty for every coefficient except the intercept (default 0). */
  ridge?: number;
}

/** A fitted model. */
export interface ForecastModel {
  /** First and last day of the history it was fitted to. */
  first: number;
  last: number;
  /** Days of history with a row. */
  days: number;
  ridge: number;
  /** Intercept, trend per week, and the effects of Monday to Saturday. */
  coefficients: number[];
}

/** A fitted model with its fit statistics on the history. */
export interface FitResult {
  model: ForecastModel;
  rmse: number;
  rSquared: number;
}

/** The expected tickets on one day. */
export interface DayForecast {
  day: number;
  tickets: number;
}

/** The design row of a day: 1, weeks since `first`, then one 0/1 column per weekday. */
export function designRow(first: number, day: number): number[] {
  const row = new Array<number>(COEFFICIENTS).fill(0);
  row[0] = 1;
  row[1] = (day - first) / 7;
  const weekday = weekdayOf(day);
  if (weekday < 6) {
    row[2 + weekday] = 1;
  }
  return row;
}

/** Root mean square error and R squared of fitted values against the actual values. */
export function residualStats(
  actual: readonly number[],
  fitted: readonly number[],
): { rmse: number; rSquared: number } {
  const n = actual.length;
  const mean = actual.reduce((sum, value) => sum + value, 0) / n;
  let squared = 0;
  let total = 0;
  for (let i = 0; i < n; i++) {
    squared += (actual[i] - fitted[i]) ** 2;
    total += (actual[i] - mean) ** 2;
  }
  return { rmse: Math.sqrt(squared / n), rSquared: total === 0 ? 1 : 1 - squared / total };
}

/** Fit the model to a history (at least MIN_HISTORY_DAYS days). */
export function fitModel(history: readonly DayCount[], options: FitOptions = {}): FitResult {
  const ridge = options.ridge ?? 0;
  if (!Number.isFinite(ridge) || ridge < 0) {
    throw new ForecastError(`the ridge penalty must be a number of at least 0, got ${ridge}`);
  }
  if (history.length < MIN_HISTORY_DAYS) {
    throw new ForecastError(
      `the history needs at least ${MIN_HISTORY_DAYS} days, got ${history.length}`,
    );
  }
  const first = history[0].day;
  const x = history.map((row) => designRow(first, row.day));
  const y = history.map((row) => row.tickets);
  const xt = transpose(x);
  const penalty = identity(COEFFICIENTS).map((row, i) =>
    row.map((value) => (i === 0 ? 0 : value * ridge)),
  );
  const lhs = multiply(xt, x).map((row, i) => row.map((value, j) => value + penalty[i][j]));
  let coefficients: number[];
  try {
    coefficients = solve(lhs, multiplyVector(xt, y));
  } catch (error) {
    if (error instanceof SingularMatrixError) {
      throw new ForecastError(
        "cannot fit the history: matrix is singular (every weekday needs at least one day)",
      );
    }
    throw error;
  }
  const model: ForecastModel = {
    first,
    last: history[history.length - 1].day,
    days: history.length,
    ridge,
    coefficients,
  };
  return { model, ...residualStats(y, multiplyVector(x, coefficients)) };
}

/** The expected tickets on a day (never below 0). */
export function predict(model: ForecastModel, day: number): number {
  const [value] = multiplyVector([designRow(model.first, day)], model.coefficients);
  return Math.max(0, value);
}

/** Forecast the `days` days that follow the last day of the history. */
export function forecast(model: ForecastModel, days: number): DayForecast[] {
  const out: DayForecast[] = [];
  for (let offset = 1; offset <= days; offset++) {
    const day = model.last + offset;
    out.push({ day, tickets: predict(model, day) });
  }
  return out;
}
