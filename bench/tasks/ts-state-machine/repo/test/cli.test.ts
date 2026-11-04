import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { run } from "../src/cli.ts";

function cli(...argv: string[]) {
  let out = "";
  let err = "";
  const status = run(argv, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { status, out, err };
}

function withOrder(state: string, fn: (path: string) => void) {
  const dir = mkdtempSync(join(tmpdir(), "orderflow-test-"));
  try {
    const path = join(dir, "order.json");
    writeFileSync(
      path,
      JSON.stringify({
        id: "SO-7",
        customer: "Test Customer",
        state,
        totalCents: 2500,
        paidCents: state === "created" ? 0 : 2500,
        address: "1 Test Road",
        history: [],
      }),
    );
    fn(path);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("show prints the summary", () => {
  withOrder("paid", (path) => {
    const result = cli("show", path);
    assert.equal(result.status, 0);
    assert.match(result.out, /^order SO-7 for Test Customer\nstate: paid\n/);
  });
});

test("events lists what the order can take", () => {
  withOrder("created", (path) => {
    assert.equal(cli("events", path).out, "pay\ncancel\n");
  });
  withOrder("refunded", (path) => {
    assert.equal(cli("events", path).out, "none\n");
  });
});

test("apply prints the change and the effects without writing", () => {
  withOrder("paid", (path) => {
    const before = readFileSync(path, "utf8");
    const result = cli("apply", path, "pack", "--at", "2027-05-04T08:00:00Z");
    assert.equal(result.status, 0);
    assert.equal(result.out, "paid -> packed\n  warehouse:pack: ask the warehouse to pack the order\n");
    assert.equal(readFileSync(path, "utf8"), before);
  });
});

test("apply --write saves the new state and the note", () => {
  withOrder("paid", (path) => {
    cli("apply", path, "pack", "--at", "2027-05-04T08:00:00Z", "--note", "fragile", "--write");
    const saved = JSON.parse(readFileSync(path, "utf8"));
    assert.equal(saved.state, "packed");
    assert.deepEqual(saved.history, [
      { at: "2027-05-04T08:00:00Z", from: "paid", event: "pack", to: "packed", note: "fragile" },
    ]);
  });
});

test("history prints the trail", () => {
  withOrder("created", (path) => {
    assert.equal(cli("history", path).out, "no history\n");
  });
});

test("an event the order cannot take exits with status 2", () => {
  withOrder("shipped", (path) => {
    const result = cli("apply", path, "cancel", "--at", "2027-05-04T08:00:00Z");
    assert.equal(result.status, 2);
    assert.equal(result.err, "orderflow: cannot cancel an order that is shipped\n");
    assert.equal(result.out, "");
  });
});

test("an unknown event or command exits with status 2", () => {
  withOrder("paid", (path) => {
    assert.equal(cli("apply", path, "teleport").err, 'orderflow: unknown event "teleport"\n');
    assert.equal(cli("apply", path, "teleport").status, 2);
  });
  const result = cli("frobnicate");
  assert.equal(result.status, 2);
  assert.match(result.err, /^usage: orderflow/);
});

test("a missing order file exits with status 2", () => {
  const result = cli("show", "/nonexistent/order.json");
  assert.equal(result.status, 2);
  assert.match(result.err, /^orderflow: \/nonexistent\/order\.json: cannot read the order/);
});
