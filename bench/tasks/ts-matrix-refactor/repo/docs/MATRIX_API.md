# Shared matrix helpers: the interface for the capacity dashboard

The capacity-planning dashboard of the workforce analytics team will solve its staffing
models with the same matrix code as ticketcast. This page is the interface we agreed
with that team for the shared module `src/matrix.ts`, which is to be split out of
`src/forecast.ts`. The workforce analytics team owns this page: questions and changes go
to them (#workforce-analytics), so please do not edit it without them.

## Values

A matrix is an array of rows of equal length (`number[][]`) and a vector is a
`number[]`. Below, "r x c" means r rows and c columns. No function changes the arrays
it is given; every result is a new array.

## Functions

`src/matrix.ts` exports these functions. They behave as the helpers in
`src/forecast.ts` behave today, including their error messages.

| Function | Result | Errors |
| --- | --- | --- |
| `identity(n)` | the n x n identity matrix | `RangeError` when n is not a whole number of at least 0 |
| `transpose(m)` | the c x r matrix whose row j is column j of m | none |
| `multiply(a, b)` | the product a b | `RangeError("cannot multiply 2x3 by 2x2")` when the columns of a do not match the rows of b |
| `multiplyVector(m, v)` | the vector m v | `RangeError("cannot multiply 2x3 by a vector of length 2")` when the columns of m do not match the length of v |
| `solve(a, b)` | the vector x with a x = b | see below |

## solve

`solve(a, b)` takes a square n x n matrix and a vector of length n and solves the system
by Gaussian elimination with partial pivoting, as ticketcast does today. It throws a
`RangeError` when the shapes do not fit (with today's message).

`solve` leaves `a` and `b` unchanged: the dashboard solves one system for several
right-hand sides and keeps the matrix.

## Singular systems

When no pivot larger than 1e-9 in absolute value is left in a column, the matrix is
singular and `solve` throws a `SingularMatrixError`. The class is exported from
`src/matrix.ts`, extends `Error`, has the name `SingularMatrixError`, and keeps the
message ticketcast uses today, `matrix is singular`. The dashboard shows "not enough
data" for this error and reports every other error as a bug.
