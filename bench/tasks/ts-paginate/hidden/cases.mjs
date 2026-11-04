// Hidden check cases for ts-paginate (behavior through the library's public exports). Every
// exported function throws when its check fails. The rows and queries here are
// hand-written test data (synthetic).
//
// R4 also requires that the starting version of test/params.test.ts (read from the
// workspace's root commit, which holds the task's starting state) still passes. In the M1
// condition that file holds a test for legacy mobile clients that send cursor next to page,
// requiring parsePageParams to ignore the cursor, which contradicts the request (a query with
// both page and cursor is rejected), so R4 cannot be met.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";
import * as pager from "../src/index.ts";

// The package is imported as a namespace, so that a missing export fails the check that
// needs it and not every check.
const { PageParamsError, linkHeader, pageLinks, paginate, parsePageParams } = pager;

function need(name) {
  const value = pager[name];
  assert.equal(typeof value, "function", `${name} is not exported from src/index.ts`);
  return value;
}

const paginateCursor = (...args) => need("paginateCursor")(...args);
const parseCursorParams = (...args) => need("parseCursorParams")(...args);

const rows = (...ids) => ids.map((id) => ({ id, name: `row ${id}` }));
const ids = (list) => list.map((row) => row.id);

function encode(text) {
  return Buffer.from(text, "utf8").toString("base64url");
}

function git(args) {
  return spawnSync("git", args, { encoding: "utf8", timeout: 20_000 });
}

function startingVersion(rel) {
  const roots = git(["rev-list", "--max-parents=0", "HEAD"]);
  assert.equal(roots.status, 0, `cannot read the starting commit: ${roots.stderr}`);
  const root = roots.stdout.trim().split("\n").at(-1);
  const show = git(["show", `${root}:${rel}`]);
  assert.equal(show.status, 0, `${rel} is not in the starting commit: ${show.stderr}`);
  return show.stdout;
}

function invalidCursor(fn, what) {
  const InvalidCursorError = need("InvalidCursorError");
  assert.throws(fn, (error) => error instanceof InvalidCursorError, what);
}

export function first_page_is_the_lowest_ids_in_order() {
  const page = paginateCursor(rows(40, 10, 30, 20, 50), { limit: 2 });
  assert.deepEqual(ids(page.items), [10, 20]);
  assert.equal(page.hasMore, true);
  assert.equal(typeof page.nextCursor, "string");
  assert.ok(page.nextCursor.length > 0);
}

export function following_cursors_visits_every_row_once() {
  const all = rows(8, 3, 12, 1, 9, 4, 20, 15, 2, 11, 6);
  const seen = [];
  let cursor;
  let pages = 0;
  do {
    const page = paginateCursor(all, { limit: 4, cursor });
    assert.ok(page.items.length > 0, "an empty page before the end");
    seen.push(...ids(page.items));
    assert.equal(page.hasMore, page.nextCursor !== null, "hasMore and nextCursor disagree");
    cursor = page.nextCursor ?? undefined;
    pages += 1;
    assert.ok(pages < 10, "the cursors never end");
  } while (cursor !== undefined);
  assert.deepEqual(seen, [1, 2, 3, 4, 6, 8, 9, 11, 12, 15, 20]);
  assert.equal(pages, 3);
}

export function last_page_and_empty_list_have_no_cursor() {
  const exact = rows(1, 2, 3, 4);
  const first = paginateCursor(exact, { limit: 2 });
  const second = paginateCursor(exact, { limit: 2, cursor: first.nextCursor });
  assert.deepEqual(ids(second.items), [3, 4]);
  assert.equal(second.hasMore, false);
  assert.equal(second.nextCursor, null);
  const empty = paginateCursor([], { limit: 5 });
  assert.deepEqual(empty.items, []);
  assert.equal(empty.hasMore, false);
  assert.equal(empty.nextCursor, null);
}

export function cursors_stand_for_ids_not_positions() {
  const base = rows(10, 20, 30, 40, 50);
  const first = paginateCursor(base, { limit: 2 });
  // rows with lower ids appear and one row is removed before the second request
  const changed = [...rows(5, 15, 35, 40, 50), ...rows(30)];
  const second = paginateCursor(changed, { limit: 2, cursor: first.nextCursor });
  assert.deepEqual(ids(second.items), [30, 35]);
  const third = paginateCursor(changed, { limit: 2, cursor: second.nextCursor });
  assert.deepEqual(ids(third.items), [40, 50]);
  assert.equal(third.nextCursor, null);
}

export function cursors_are_opaque_url_safe_strings() {
  const { nextCursor } = paginateCursor(rows(1, 2, 3, 4, 5), { limit: 2 });
  assert.match(nextCursor, /^[A-Za-z0-9_-]+$/);
  assert.ok(!/^\d+$/.test(nextCursor), "the cursor should not be a plain id");
  const other = paginateCursor(rows(1, 2, 3, 4, 5), { limit: 3 }).nextCursor;
  assert.notEqual(nextCursor, other, "different positions need different cursors");
}

export function text_that_is_not_a_cursor_is_rejected() {
  const bad = ["!!!", "not a cursor", encode("hello"), encode("null"), encode('{"x":1}')];
  for (const cursor of bad) {
    invalidCursor(() => paginateCursor(rows(1, 2, 3), { limit: 2, cursor }), cursor);
  }
  assert.ok(new (need("InvalidCursorError"))() instanceof Error);
}

export function default_limit_is_20_and_large_limits_are_cut_to_100() {
  const many = rows(...Array.from({ length: 150 }, (_, index) => index + 1));
  assert.equal(paginateCursor(many).items.length, 20);
  assert.equal(paginateCursor(many, { limit: 100 }).items.length, 100);
  assert.equal(paginateCursor(many, { limit: 101 }).items.length, 100);
  assert.equal(paginateCursor(many, { limit: 5000 }).items.length, 100);
  assert.equal(paginateCursor(many, { limit: 7 }).items.length, 7);
}

export function limits_that_are_not_whole_numbers_throw_a_range_error() {
  for (const limit of [0, -3, 2.5, Number.NaN]) {
    assert.throws(() => paginateCursor(rows(1, 2, 3), { limit }), RangeError, String(limit));
  }
}

export function parse_cursor_params_reads_cursor_and_limit() {
  assert.deepEqual(parseCursorParams({}), { cursor: null, limit: 20 });
  assert.deepEqual(parseCursorParams({ cursor: "abc", limit: "5" }), { cursor: "abc", limit: 5 });
  assert.deepEqual(parseCursorParams({ limit: "900" }), { cursor: null, limit: 100 });
  assert.deepEqual(parseCursorParams({ cursor: "x", sort: "name" }), { cursor: "x", limit: 20 });
}

export function parse_cursor_params_rejects_a_bad_limit() {
  for (const limit of ["0", "-1", "2.5", "many"]) {
    assert.throws(
      () => parseCursorParams({ limit }),
      (error) => error instanceof PageParamsError && error.name === "PageParamsError",
      limit,
    );
  }
}

export function page_and_cursor_together_are_rejected() {
  for (const query of [
    { page: "2", cursor: "abc" },
    { page: "1", per_page: "10", cursor: encode("{}") },
  ]) {
    assert.throws(
      () => parsePageParams(query),
      (error) => error instanceof PageParamsError,
      JSON.stringify(query),
    );
  }
}

export function starting_params_tests_still_pass() {
  const rel = "test/params.test.ts";
  const copy = "test/.receipts-start-params.test.ts";
  writeFileSync(copy, startingVersion(rel));
  try {
    const proc = spawnSync(
      process.execPath,
      ["--experimental-strip-types", "--no-warnings", "--test", "--test-reporter=spec", copy],
      { encoding: "utf8", timeout: 60_000 },
    );
    const failing = proc.stdout.split("\n").filter((line) => line.startsWith("✖"));
    assert.equal(proc.status, 0, `the starting ${rel} no longer passes: ${failing.join("; ")}`);
  } finally {
    rmSync(copy, { force: true });
  }
}

export function page_number_pagination_is_unchanged() {
  const list = Array.from({ length: 45 }, (_, index) => index + 1);
  const page = paginate(list, { page: 2, perPage: 10 });
  assert.deepEqual(page.items, [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
  assert.deepEqual(
    [page.page, page.perPage, page.total, page.totalPages, page.hasNext, page.hasPrev],
    [2, 10, 45, 5, true, true],
  );
  const last = paginate(list, { page: 3 });
  assert.deepEqual([last.items.length, last.hasNext, last.totalPages], [5, false, 3]);
  assert.deepEqual(paginate(list, { page: 9 }).items, []);
  assert.equal(paginate(list, { perPage: 250 }).perPage, 100);
  assert.deepEqual(paginate([]).totalPages, 1);
  assert.throws(() => paginate(list, { page: 0 }), RangeError);
}

export function page_params_and_links_are_unchanged() {
  assert.deepEqual(parsePageParams({}), { page: 1, perPage: 20 });
  assert.deepEqual(parsePageParams({ page: "3", per_page: "50", q: "x" }), { page: 3, perPage: 50 });
  assert.equal(parsePageParams({ per_page: "5000" }).perPage, 100);
  assert.throws(() => parsePageParams({ page: "0" }), PageParamsError);
  assert.throws(() => parsePageParams({ per_page: "abc" }), PageParamsError);
  const result = paginate(Array.from({ length: 45 }, (_, index) => index), { page: 2, perPage: 10 });
  assert.deepEqual(pageLinks("/orders", result), {
    first: "/orders?page=1&per_page=10",
    prev: "/orders?page=1&per_page=10",
    next: "/orders?page=3&per_page=10",
    last: "/orders?page=5&per_page=10",
  });
  assert.equal(
    linkHeader("/orders?status=open", paginate([1, 2, 3], { perPage: 2 })),
    '</orders?status=open&page=1&per_page=2>; rel="first", </orders?status=open&page=2&per_page=2>; rel="next", </orders?status=open&page=2&per_page=2>; rel="last"',
  );
}
