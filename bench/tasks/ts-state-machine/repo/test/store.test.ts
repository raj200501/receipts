import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { loadOrder, saveOrder } from "../src/store.ts";
import { TransitionError } from "../src/types.ts";

function inTempDir(fn: (dir: string) => void) {
  const dir = mkdtempSync(join(tmpdir(), "orderflow-test-"));
  try {
    fn(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const VALID = {
  id: "SO-5",
  customer: "Test Customer",
  state: "paid",
  totalCents: 1000,
  paidCents: 1000,
  history: [{ at: "2027-05-03T10:00:00Z", from: "created", event: "pay", to: "paid" }],
};

test("loads an order file", () => {
  inTempDir((dir) => {
    const path = join(dir, "o.json");
    writeFileSync(path, JSON.stringify(VALID));
    const order = loadOrder(path);
    assert.equal(order.state, "paid");
    assert.equal(order.history.length, 1);
    assert.equal(order.address, undefined);
  });
});

test("history is optional", () => {
  inTempDir((dir) => {
    const path = join(dir, "o.json");
    writeFileSync(path, JSON.stringify({ ...VALID, history: undefined }));
    assert.deepEqual(loadOrder(path).history, []);
  });
});

test("an unknown state names the file", () => {
  inTempDir((dir) => {
    const path = join(dir, "o.json");
    writeFileSync(path, JSON.stringify({ ...VALID, state: "lost" }));
    assert.throws(() => loadOrder(path), (error) => error instanceof TransitionError && error.message.startsWith(`${path}: state must be one of created, paid`));
  });
});

test("amounts must be whole cents", () => {
  inTempDir((dir) => {
    const path = join(dir, "o.json");
    writeFileSync(path, JSON.stringify({ ...VALID, totalCents: 10.5 }));
    assert.throws(() => loadOrder(path), /totalCents must be a whole number of cents/);
  });
});

test("a file that is not JSON is an error", () => {
  inTempDir((dir) => {
    const path = join(dir, "o.json");
    writeFileSync(path, "{nope");
    assert.throws(() => loadOrder(path), /cannot read the order/);
  });
});

test("saving writes indented JSON with a final newline", () => {
  inTempDir((dir) => {
    const path = join(dir, "o.json");
    writeFileSync(path, JSON.stringify(VALID));
    saveOrder(path, loadOrder(path));
    const text = readFileSync(path, "utf8");
    assert.ok(text.endsWith("}\n"));
    assert.match(text, /^\{\n {2}"id": "SO-5",/);
  });
});
