import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SingularMatrixError,
  identity,
  multiply,
  multiplyVector,
  solve,
  transpose,
} from "../src/matrix.ts";

test("identity has ones on the diagonal", () => {
  assert.deepEqual(identity(3), [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ]);
  assert.deepEqual(identity(0), []);
  assert.throws(() => identity(-1), {
    name: "RangeError",
    message: "identity size must be a whole number of at least 0, got -1",
  });
});

test("transpose swaps rows and columns", () => {
  assert.deepEqual(
    transpose([
      [1, 2, 3],
      [4, 5, 6],
    ]),
    [
      [1, 4],
      [2, 5],
      [3, 6],
    ],
  );
  assert.deepEqual(transpose([]), []);
});

test("multiply and multiplyVector check the shapes", () => {
  const a = [
    [1, 2, 3],
    [4, 5, 6],
  ];
  assert.deepEqual(multiply(a, transpose(a)), [
    [14, 32],
    [32, 77],
  ]);
  assert.deepEqual(multiplyVector(a, [1, 0, -1]), [-2, -2]);
  assert.throws(() => multiply(a, a), { name: "RangeError", message: "cannot multiply 2x3 by 2x3" });
  assert.throws(() => multiplyVector(a, [1, 2]), {
    name: "RangeError",
    message: "cannot multiply 2x3 by a vector of length 2",
  });
});

test("solve pivots and leaves its arguments unchanged", () => {
  const a = [
    [0, 2, 1],
    [1, -1, 0],
    [3, 0, 2],
  ];
  const b = [7, -1, 9];
  const x = solve(a, b);
  [1, 2, 3].forEach((expected, i) => assert.ok(Math.abs(x[i] - expected) < 1e-12));
  assert.deepEqual(a, [
    [0, 2, 1],
    [1, -1, 0],
    [3, 0, 2],
  ]);
  assert.deepEqual(b, [7, -1, 9]);
});

test("a singular matrix throws a SingularMatrixError", () => {
  assert.throws(
    () =>
      solve(
        [
          [1, 2],
          [2, 4],
        ],
        [3, 6],
      ),
    (error: unknown) =>
      error instanceof SingularMatrixError &&
      error.name === "SingularMatrixError" &&
      error.message === "matrix is singular",
  );
  assert.throws(() => solve([[1, 2]], [1]), {
    name: "RangeError",
    message: "cannot solve a 1x2 system with a vector of length 1",
  });
});
