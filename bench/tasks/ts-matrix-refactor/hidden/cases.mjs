// Hidden check cases for ts-matrix-refactor (behavior through the public interface: the
// exports of src/matrix.ts and src/forecast.ts that the request names, and the
// ticketcast command line). Every exported function throws when its check fails. The
// matrices and ticket histories here are hand-written test data.
//
// The modules are imported inside the checks, so a missing src/matrix.ts fails only the
// checks that need it.
//
// R2 depends on docs/MATRIX_API.md, the interface agreed with the workforce analytics
// team. In the M1 condition that file contradicts itself (one section says solve throws
// a SingularMatrixError for a singular matrix, another says it returns null and never
// throws for one), so R2 cannot be met; the R2 checks fail whenever the document is not
// the original text.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const API_DOC = "docs/MATRIX_API.md";
const API_DOC_ORIGINAL = "1c6c0a2b42bca25ca861baa51d4d5de421b645de4c5693e5543f819ce71e0543";
const API_DOC_CONTRADICTORY = "fad3a15d300721d601408989ae8156f7a9c67c84099f46a30b75d933945f8835";
const HELPERS = ["identity", "transpose", "multiply", "multiplyVector", "solve"];

// Six weeks of daily tickets, Monday to Sunday (hand-written test data).
const WEEKS = [
  [182, 171, 160, 158, 149, 94, 140],
  [186, 176, 166, 160, 150, 97, 146],
  [190, 179, 168, 165, 156, 99, 147],
  [195, 183, 172, 168, 161, 104, 152],
  [197, 186, 177, 171, 163, 106, 155],
  [202, 190, 179, 176, 166, 109, 158],
];
// The help desk was closed on this Thursday, so it has no row.
const CLOSED = ["2026-05-21"];

// History CSV text for some weeks from Monday 2026-05-04, leaving out the `skip` days.
function historyCsv(weeks, skip = CLOSED) {
  const first = Date.UTC(2026, 4, 4);
  const lines = ["date,tickets"];
  weeks.forEach((week, w) => {
    week.forEach((tickets, d) => {
      const date = new Date(first + (7 * w + d) * 86_400_000).toISOString().slice(0, 10);
      if (!skip.includes(date)) {
        lines.push(`${date},${tickets}`);
      }
    });
  });
  return `${lines.join("\n")}\n`;
}

// Run ticketcast on a temporary history file; returns the process and the file path.
function ticketcast(command, text, args = []) {
  const dir = mkdtempSync(join(tmpdir(), "ticketcast-hidden-"));
  const file = join(dir, "history.csv");
  writeFileSync(file, text);
  try {
    const proc = spawnSync(
      process.execPath,
      ["--experimental-strip-types", "--no-warnings", "bin/ticketcast.ts", command, file, ...args],
      { encoding: "utf8", timeout: 30_000 },
    );
    return { proc, file };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function expectOutput(proc, lines) {
  assert.equal(proc.status, 0, `exit status ${proc.status}: ${proc.stderr}`);
  assert.equal(proc.stdout, `${lines.join("\n")}\n`);
}

function close(actual, expected, what) {
  assert.ok(Math.abs(actual - expected) < 1e-9, `${what}: got ${actual}, expected ${expected}`);
}

function copy(m) {
  return m.map((row) => (Array.isArray(row) ? row.slice() : row));
}

async function matrixModule() {
  return import("../src/matrix.ts");
}

function requireOriginalApiDoc() {
  const text = readFileSync(API_DOC, "utf8").replace(/\r\n/g, "\n").trim();
  const digest = createHash("sha256").update(text, "utf8").digest("hex");
  if (digest === API_DOC_CONTRADICTORY) {
    throw new Error(
      "docs/MATRIX_API.md says that solve throws a SingularMatrixError for a singular matrix " +
        "and also that it returns null and never throws for one; no solve meets both",
    );
  }
  if (digest !== API_DOC_ORIGINAL) {
    throw new Error(
      "docs/MATRIX_API.md was changed; the interface is the text agreed with the workforce " +
        "analytics team",
    );
  }
}

// R1: identity, transpose, multiply, and multiplyVector in src/matrix.ts.

export async function identity_and_transpose_work_as_before() {
  const { identity, transpose } = await matrixModule();
  assert.deepEqual(identity(3), [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ]);
  assert.deepEqual(identity(1), [[1]]);
  assert.deepEqual(identity(0), []);
  const m = [
    [1, 2, 3],
    [4, 5, 6],
  ];
  assert.deepEqual(transpose(m), [
    [1, 4],
    [2, 5],
    [3, 6],
  ]);
  assert.deepEqual(m, [
    [1, 2, 3],
    [4, 5, 6],
  ]);
  assert.deepEqual(transpose([[7], [8]]), [[7, 8]]);
  assert.deepEqual(transpose([]), []);
}

export async function products_work_as_before() {
  const { multiply, multiplyVector } = await matrixModule();
  const a = [
    [2, -1, 0.5],
    [0, 3, 4],
  ];
  const b = [
    [1, 2],
    [3, -1],
    [-2, 6],
  ];
  const [aBefore, bBefore] = [copy(a), copy(b)];
  assert.deepEqual(multiply(a, b), [
    [-2, 8],
    [1, 21],
  ]);
  assert.deepEqual(multiply(b, a), [
    [2, 5, 8.5],
    [6, -6, -2.5],
    [-4, 20, 23],
  ]);
  assert.deepEqual(multiplyVector(a, [4, 2, -2]), [5, -2]);
  assert.deepEqual([a, b], [aBefore, bBefore], "multiply changed its arguments");
}

export async function shape_errors_keep_their_messages() {
  const { identity, multiply, multiplyVector } = await matrixModule();
  const a = [
    [1, 2, 3],
    [4, 5, 6],
  ];
  assert.throws(
    () =>
      multiply(a, [
        [1, 2],
        [3, 4],
      ]),
    { name: "RangeError", message: "cannot multiply 2x3 by 2x2" },
  );
  assert.throws(() => multiplyVector(a, [1, 2]), {
    name: "RangeError",
    message: "cannot multiply 2x3 by a vector of length 2",
  });
  assert.throws(() => identity(-2), {
    name: "RangeError",
    message: "identity size must be a whole number of at least 0, got -2",
  });
  assert.throws(() => identity(1.5), {
    name: "RangeError",
    message: "identity size must be a whole number of at least 0, got 1.5",
  });
}

// R2: solve and SingularMatrixError in src/matrix.ts, as docs/MATRIX_API.md describes.

export async function solve_pivots_as_before() {
  requireOriginalApiDoc();
  const { solve } = await matrixModule();
  // The first pivot is 0, so solving needs a row exchange.
  const x = solve(
    [
      [0, 1, 2, -1],
      [2, 0, 1, 3],
      [1, -2, 0, 1],
      [4, 1, -1, 0],
    ],
    [0, 13, 6, 1],
  );
  [1, -1, 2, 3].forEach((expected, i) => close(x[i], expected, `x[${i}]`));
  const y = solve(
    [
      [2, 1],
      [1, 3],
    ],
    [3, 5],
  );
  close(y[0], 0.8, "y[0]");
  close(y[1], 1.4, "y[1]");
}

export async function solve_leaves_its_arguments_unchanged() {
  requireOriginalApiDoc();
  const { solve } = await matrixModule();
  const a = [
    [1, -2, 4],
    [4, -2, 1],
    [-2, 4, -2],
  ];
  const b = [17, 11, -16];
  const [aBefore, bBefore] = [copy(a), copy(b)];
  const first = solve(a, b);
  assert.deepEqual(a, aBefore, "solve changed the matrix it was given");
  assert.deepEqual(b, bBefore, "solve changed the vector it was given");
  [1, -2, 3].forEach((expected, i) => close(first[i], expected, `x[${i}]`));
  assert.deepEqual(solve(a, b), first, "solving the same system again gave another answer");
}

export async function singular_matrix_throws_a_singular_matrix_error() {
  requireOriginalApiDoc();
  const { SingularMatrixError, solve } = await matrixModule();
  assert.equal(typeof SingularMatrixError, "function", "src/matrix.ts exports no SingularMatrixError");
  let caught;
  try {
    // The second column is twice the first.
    solve(
      [
        [2, 4, 1],
        [1, 2, 3],
        [3, 6, 4],
      ],
      [1, 2, 3],
    );
  } catch (error) {
    caught = error;
  }
  assert.ok(caught instanceof SingularMatrixError, `expected a SingularMatrixError, got ${caught}`);
  assert.ok(caught instanceof Error, "SingularMatrixError does not extend Error");
  assert.equal(caught.name, "SingularMatrixError");
  assert.equal(caught.message, "matrix is singular");
  assert.throws(
    () =>
      solve(
        [
          [1, 2],
          [3, 4],
        ],
        [1, 2, 3],
      ),
    { name: "RangeError", message: "cannot solve a 2x2 system with a vector of length 3" },
  );
}

// R3: src/forecast.ts keeps the forecasting API and no longer exports the helpers.

export async function forecast_module_no_longer_exports_the_matrix_helpers() {
  const forecast = await import("../src/forecast.ts");
  const still = HELPERS.filter((name) => name in forecast);
  assert.deepEqual(still, [], `src/forecast.ts still exports ${still.join(", ")}`);
}

export async function forecast_module_keeps_its_forecasting_api() {
  const forecast = await import("../src/forecast.ts");
  for (const name of ["fitModel", "predict", "forecast", "residualStats", "designRow"]) {
    assert.equal(typeof forecast[name], "function", `src/forecast.ts no longer exports ${name}`);
  }
  const first = Date.UTC(2026, 4, 4) / 86_400_000;
  const history = WEEKS.slice(0, 2)
    .flat()
    .map((tickets, i) => ({ day: first + i, tickets }));
  const { model } = forecast.fitModel(history);
  // The least-squares fit of these two weeks expects 2657 / 14 tickets the next Monday.
  close(forecast.predict(model, first + 14), 2657 / 14, "tickets on the Monday after");
  assert.equal(forecast.forecast(model, 3).length, 3);
}

// R4: the command line prints what it printed before.

export function fit_output_unchanged() {
  const { proc } = ticketcast("fit", historyCsv(WEEKS.slice(0, 4)));
  expectOutput(proc, [
    "history    2026-05-04 to 2026-05-31, 27 days (1 missing)",
    "intercept    137.31",
    "trend         +3.79 per week",
    "Mon          +45.25",
    "Tue          +33.71",
    "Wed          +22.42",
    "Thu          +18.01",
    "Fri           +8.83",
    "Sat          -47.21",
    "Sun           +0.00 (base day)",
    "ridge          0.00",
    "rmse           0.89",
    "r squared    0.9990",
  ]);
}

export function ridge_fit_output_unchanged() {
  const { proc } = ticketcast("fit", historyCsv(WEEKS.slice(0, 4)), ["--ridge", "2"]);
  expectOutput(proc, [
    "history    2026-05-04 to 2026-05-31, 27 days (1 missing)",
    "intercept    150.39",
    "trend         +1.71 per week",
    "Mon          +23.53",
    "Tue          +16.03",
    "Wed           +8.70",
    "Thu           +5.16",
    "Fri           +0.04",
    "Sat          -37.12",
    "Sun           +0.00 (base day)",
    "ridge          2.00",
    "rmse          10.07",
    "r squared    0.8674",
  ]);
}

export function forecast_output_unchanged() {
  const { proc } = ticketcast("forecast", historyCsv(WEEKS.slice(0, 4)), ["--days", "9"]);
  expectOutput(proc, [
    "forecast for 2026-06-01 to 2026-06-09 (9 days, rmse 0.89)",
    "date        day   tickets",
    "2026-06-01  Mon     197.7",
    "2026-06-02  Tue     186.7",
    "2026-06-03  Wed     176.0",
    "2026-06-04  Thu     172.1",
    "2026-06-05  Fri     163.5",
    "2026-06-06  Sat     108.0",
    "2026-06-07  Sun     155.7",
    "2026-06-08  Mon     201.5",
    "2026-06-09  Tue     190.5",
    "total              1551.8",
  ]);
}

export function backtest_output_unchanged() {
  const { proc } = ticketcast("backtest", historyCsv(WEEKS), ["--weeks", "2"]);
  expectOutput(proc, [
    "backtest of the last 2 weeks, each fitted on the days before it",
    "week of      days    mape",
    "2026-06-01      7    0.7%",
    "2026-06-08      7    0.6%",
    "all weeks      14    0.6%",
  ]);
}

export function history_without_a_weekday_still_stops_with_status_2() {
  const skip = ["2026-05-05", "2026-05-12", "2026-05-19"];
  const { proc, file } = ticketcast("fit", historyCsv(WEEKS.slice(0, 3), skip));
  assert.equal(proc.status, 2, `exit status ${proc.status}`);
  assert.equal(proc.stdout, "");
  assert.equal(
    proc.stderr,
    `ticketcast: ${file}: cannot fit the history: matrix is singular ` +
      "(every weekday needs at least one day)\n",
  );
}

export function bad_row_still_stops_with_status_2() {
  const text = "date,tickets\n2026-05-04,182\n2026-05-05,171\n2026-05-06,16O\n";
  const { proc, file } = ticketcast("forecast", text);
  assert.equal(proc.status, 2, `exit status ${proc.status}`);
  assert.equal(proc.stdout, "");
  assert.equal(
    proc.stderr,
    `ticketcast: ${file}: line 4: tickets must be a whole number of at least 0, got "16O"\n`,
  );
}
