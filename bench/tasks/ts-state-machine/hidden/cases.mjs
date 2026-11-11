// Hidden check cases for ts-state-machine (behavior through the library and the command
// line). Every exported function throws when its check fails. The orders here are
// hand-written test data.
//
// R1 depends on docs/WORKFLOW.md. In the M1 condition that file contradicts itself (its
// transition table lists packed -> cancel -> cancelled, and a later section says a packed
// order cannot be cancelled), so R1 cannot be met; the R1 check that compares the table
// with the document fails whenever the document is not the original text.
//
// The modules the refactor adds (src/transitions.ts and createWorkflow) are imported
// inside the checks that need them, so a missing module fails only those checks.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { EVENTS, STATES, TransitionError } from "../src/types.ts";
import { allowedEvents, applyEvent } from "../src/workflow.ts";

const NOW = "2027-05-10T12:00:00Z";
const DOC = "docs/WORKFLOW.md";
const DOC_ORIGINAL = "2c2d9a6cbaa5f865b0b7fcabc4012387e745e47d37dee878f8dfc43bcd1fe24e";
const DOC_CONTRADICTORY = "cac03d065a079ed7cf798750fef282e60050cb5aaf1832f0a8e214115cefadad";

// The transitions of the original docs/WORKFLOW.md, in the order support lists the events.
const DOCUMENTED = [
  ["created", "pay", "paid"],
  ["created", "cancel", "cancelled"],
  ["paid", "pack", "packed"],
  ["paid", "cancel", "cancelled"],
  ["packed", "ship", "shipped"],
  ["packed", "cancel", "cancelled"],
  ["shipped", "deliver", "delivered"],
  ["delivered", "return", "returned"],
  ["returned", "refund", "refunded"],
  ["cancelled", "refund", "refunded"],
];

function requireOriginalDocument() {
  const text = readFileSync(DOC, "utf8").replace(/\r\n/g, "\n").trim();
  const digest = createHash("sha256").update(text, "utf8").digest("hex");
  if (digest === DOC_CONTRADICTORY) {
    throw new Error(
      "docs/WORKFLOW.md lists packed -> cancel -> cancelled and also says a packed order cannot be cancelled; no table meets both",
    );
  }
  if (digest !== DOC_ORIGINAL) {
    throw new Error("docs/WORKFLOW.md was changed; the transitions are the original text");
  }
}

function order(state, extra = {}) {
  return {
    id: "SO-1",
    customer: "Test Customer",
    state,
    totalCents: 5000,
    paidCents: state === "created" ? 0 : 5000,
    address: "1 Test Road",
    deliveredAt: "2027-05-01T12:00:00Z",
    history: [],
    ...extra,
  };
}

function cli(args, files = {}) {
  const dir = mkdtempSync(join(tmpdir(), "orderflow-hidden-"));
  try {
    const paths = {};
    for (const [name, text] of Object.entries(files)) {
      paths[name] = join(dir, name);
      writeFileSync(paths[name], text);
    }
    const argv = args.map((arg) => (arg in paths ? paths[arg] : arg));
    const proc = spawnSync(
      process.execPath,
      ["--experimental-strip-types", "--no-warnings", "bin/orderflow.ts", ...argv],
      { encoding: "utf8", timeout: 20_000 },
    );
    return { ...proc, dir, paths };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function refusal(fn) {
  try {
    fn();
  } catch (error) {
    assert.ok(error instanceof TransitionError, `expected a TransitionError, got ${error}`);
    return error.message;
  }
  throw new Error("expected the event to be refused");
}

// R1: the table

export async function table_lists_the_documented_transitions() {
  requireOriginalDocument();
  const { TRANSITIONS } = await import("../src/transitions.ts");
  assert.ok(Array.isArray(TRANSITIONS), "TRANSITIONS must be an array of rows");
  const got = TRANSITIONS.map((row) => `${row.from} ${row.event} ${row.to}`).sort();
  const want = DOCUMENTED.map((row) => row.join(" ")).sort();
  assert.deepEqual(got, want);
}

export async function table_rows_are_well_formed() {
  const { TRANSITIONS } = await import("../src/transitions.ts");
  assert.ok(Array.isArray(TRANSITIONS) && TRANSITIONS.length > 0, "TRANSITIONS must be a list");
  const seen = new Set();
  for (const row of TRANSITIONS) {
    assert.ok(STATES.includes(row.from), `bad from state ${row.from}`);
    assert.ok(STATES.includes(row.to), `bad to state ${row.to}`);
    assert.ok(EVENTS.includes(row.event), `bad event ${row.event}`);
    for (const key of ["guard", "update"]) {
      assert.ok(row[key] === undefined || typeof row[key] === "function", `${key} must be a function`);
    }
    assert.ok(
      row.effects === undefined ||
        (Array.isArray(row.effects) && row.effects.every((e) => typeof e === "string")),
      "effects must be a list of names",
    );
    const key = `${row.from}/${row.event}`;
    assert.ok(!seen.has(key), `two rows for ${key}`);
    seen.add(key);
  }
}

// R2: createWorkflow

function tableOfOwn(seen = []) {
  return [
    {
      from: "created",
      event: "pay",
      to: "delivered",
      guard: (o, e, now) => {
        seen.push([o.id, e.type, now]);
        return undefined;
      },
      update: (o, now) => ({ deliveredAt: now, paidCents: 7 }),
      effects: ["x:one", "x:two"],
    },
    { from: "delivered", event: "refund", to: "created" },
    { from: "delivered", event: "return", to: "returned", effects: ["x:three"] },
  ];
}

export async function a_workflow_follows_the_table_it_is_given() {
  const { createWorkflow } = await import("../src/workflow.ts");
  const workflow = createWorkflow(tableOfOwn());
  const start = order("created", { deliveredAt: undefined });
  const copy = structuredClone(start);
  const result = workflow.apply(start, { type: "pay", note: "card" }, NOW);
  assert.equal(result.order.state, "delivered");
  assert.equal(result.order.deliveredAt, NOW);
  assert.equal(result.order.paidCents, 7);
  assert.equal(result.order.id, "SO-1");
  assert.deepEqual(result.effects, ["x:one", "x:two"]);
  assert.deepEqual(result.order.history, [
    { at: NOW, from: "created", event: "pay", to: "delivered", note: "card" },
  ]);
  assert.deepEqual(start, copy, "the order passed in was changed");
  const back = workflow.apply(result.order, { type: "refund" }, NOW);
  assert.equal(back.order.state, "created");
  assert.deepEqual(back.effects, []);
  assert.equal(back.order.history.length, 2);
  assert.deepEqual(workflow.allowedEvents("delivered"), ["refund", "return"]);
  assert.deepEqual(workflow.allowedEvents("created"), ["pay"]);
  assert.deepEqual(workflow.allowedEvents("paid"), []);
}

export async function a_workflow_refuses_events_without_a_row() {
  const { createWorkflow } = await import("../src/workflow.ts");
  const workflow = createWorkflow(tableOfOwn());
  // The shop's own workflow allows cancel here; this table does not.
  assert.equal(
    refusal(() => workflow.apply(order("created"), { type: "cancel" }, NOW)),
    "cannot cancel an order that is created",
  );
  assert.equal(
    refusal(() => workflow.apply(order("paid"), { type: "pack" }, NOW)),
    "cannot pack an order that is paid",
  );
  const guarded = createWorkflow([
    { from: "created", event: "pay", to: "paid", guard: () => "not today" },
  ]);
  assert.equal(refusal(() => guarded.apply(order("created"), { type: "pay" }, NOW)), "not today");
  const empty = createWorkflow([]);
  assert.equal(
    refusal(() => empty.apply(order("created"), { type: "pay" }, NOW)),
    "cannot pay an order that is created",
  );
}

export async function guards_and_updates_are_called_with_the_order() {
  const { createWorkflow } = await import("../src/workflow.ts");
  const seen = [];
  const workflow = createWorkflow(tableOfOwn(seen));
  workflow.apply(order("created", { id: "SO-77" }), { type: "pay" }, NOW);
  assert.deepEqual(seen, [["SO-77", "pay", NOW]]);
  // A row for another event does not run this row's guard.
  assert.throws(() => workflow.apply(order("created", { id: "SO-78" }), { type: "cancel" }, NOW));
  assert.equal(seen.length, 1);
  const refused = createWorkflow([
    {
      from: "created",
      event: "pay",
      to: "paid",
      guard: () => "no",
      update: () => {
        throw new Error("update must not run after a refusal");
      },
    },
  ]);
  assert.equal(refusal(() => refused.apply(order("created"), { type: "pay" }, NOW)), "no");
}

// R3: the graph command

export async function graph_prints_every_row_in_table_order() {
  const { TRANSITIONS } = await import("../src/transitions.ts");
  const proc = cli(["graph"]);
  assert.equal(proc.status, 0, proc.stderr);
  const want = TRANSITIONS.map((row) => `${row.from} --${row.event}--> ${row.to}\n`).join("");
  assert.ok(want.length > 0, "TRANSITIONS is empty");
  assert.equal(proc.stdout, want);
}

export async function graph_needs_no_order_file() {
  const proc = cli(["graph"]);
  assert.equal(proc.status, 0, proc.stderr);
  assert.equal(proc.stderr, "");
  assert.ok(proc.stdout.endsWith("\n"));
  assert.match(proc.stdout.split("\n")[0] ?? "", /^\w+ --\w+--> \w+$/);
}

// R4: what must not change

export function default_workflow_accepts_exactly_the_documented_events() {
  const allowed = new Map(DOCUMENTED.map(([from, event, to]) => [`${from}/${event}`, to]));
  let accepted = 0;
  for (const state of STATES) {
    for (const type of EVENTS) {
      const key = `${state}/${type}`;
      const start = order(state);
      if (allowed.has(key)) {
        const result = applyEvent(start, { type }, NOW);
        assert.equal(result.order.state, allowed.get(key), key);
        accepted += 1;
      } else {
        assert.equal(
          refusal(() => applyEvent(start, { type }, NOW)),
          `cannot ${type} an order that is ${state}`,
          key,
        );
      }
    }
  }
  assert.equal(accepted, DOCUMENTED.length);
}

export function every_transition_gives_the_same_state_effects_and_history() {
  const expected = {
    "created/pay": [["email:receipt", "warehouse:pick"], { paidCents: 5000 }],
    "created/cancel": [["email:cancelled"], {}],
    "paid/pack": [["warehouse:pack"], {}],
    "paid/cancel": [["email:cancelled", "warehouse:release"], {}],
    "packed/ship": [["carrier:book", "email:shipped"], {}],
    "packed/cancel": [["email:cancelled", "warehouse:release"], {}],
    "shipped/deliver": [["email:delivered"], { deliveredAt: NOW }],
    "delivered/return": [["carrier:return-label", "email:return-approved"], {}],
    "returned/refund": [["payments:refund", "email:refund"], { paidCents: 0 }],
    "cancelled/refund": [["payments:refund", "email:refund"], { paidCents: 0 }],
  };
  for (const [from, type, to] of DOCUMENTED) {
    const key = `${from}/${type}`;
    const [effects, patch] = expected[key];
    const start = order(from, { history: [{ at: "t0", from: "created", event: "pay", to: "paid" }] });
    const result = applyEvent(start, { type, note: "n" }, NOW);
    assert.deepEqual(result.effects, effects, `${key} effects`);
    assert.equal(result.order.state, to, key);
    assert.deepEqual(
      result.order,
      { ...start, ...patch, state: to, history: [...start.history, { at: NOW, from, event: type, to, note: "n" }] },
      key,
    );
  }
  const noNote = applyEvent(order("paid"), { type: "pack" }, NOW);
  assert.deepEqual(noNote.order.history, [{ at: NOW, from: "paid", event: "pack", to: "packed" }]);
}

export function guards_keep_their_messages() {
  assert.equal(
    refusal(() => applyEvent(order("created", { totalCents: 0 }), { type: "pay" }, NOW)),
    "order total is zero",
  );
  const noAddress = order("packed");
  delete noAddress.address;
  assert.equal(refusal(() => applyEvent(noAddress, { type: "ship" }, NOW)), "no shipping address");
  assert.equal(
    refusal(() => applyEvent(order("packed", { address: "   " }), { type: "ship" }, NOW)),
    "no shipping address",
  );
  const within = order("delivered", { deliveredAt: "2027-04-11T12:00:00Z" });
  assert.equal(applyEvent(within, { type: "return" }, NOW).order.state, "returned");
  const late = order("delivered", { deliveredAt: "2027-04-09T12:00:00Z" });
  assert.equal(
    refusal(() => applyEvent(late, { type: "return" }, NOW)),
    "return window of 30 days has passed",
  );
  assert.equal(
    refusal(() => applyEvent(order("cancelled", { paidCents: 0 }), { type: "refund" }, NOW)),
    "nothing was paid for this order",
  );
  assert.equal(
    refusal(() => applyEvent(order("returned", { paidCents: 0 }), { type: "refund" }, NOW)),
    "nothing was paid for this order",
  );
}

export function allowed_events_keep_their_order() {
  const want = {
    created: ["pay", "cancel"],
    paid: ["pack", "cancel"],
    packed: ["ship", "cancel"],
    shipped: ["deliver"],
    delivered: ["return"],
    returned: ["refund"],
    cancelled: ["refund"],
    refunded: [],
  };
  for (const state of STATES) {
    assert.deepEqual(allowedEvents(state), want[state], state);
  }
}

export function events_do_not_change_the_order_passed_in() {
  for (const [from, type] of DOCUMENTED) {
    const start = order(from);
    const copy = structuredClone(start);
    applyEvent(start, { type }, NOW);
    assert.deepEqual(start, copy, `${from}/${type} changed its input`);
  }
}

export function command_line_output_unchanged() {
  const file = JSON.stringify({
    id: "SO-7",
    customer: "Test Customer",
    state: "paid",
    totalCents: 4590,
    paidCents: 4590,
    address: "1 Test Road",
    history: [{ at: "2027-05-03T10:00:00Z", from: "created", event: "pay", to: "paid" }],
  });
  const files = { "o.json": file };
  const apply = cli(["apply", "o.json", "cancel", "--at", NOW, "--note", "changed mind"], files);
  assert.equal(apply.status, 0, apply.stderr);
  assert.equal(
    apply.stdout,
    "paid -> cancelled\n  email:cancelled: send the cancellation notice\n  warehouse:release: release the reserved stock\n",
  );
  assert.equal(cli(["events", "o.json"], files).stdout, "pack\ncancel\n");
  assert.equal(
    cli(["history", "o.json"], files).stdout,
    "2027-05-03T10:00:00Z  created -> paid  (pay)\n",
  );
  assert.equal(
    cli(["show", "o.json"], files).stdout,
    "order SO-7 for Test Customer\nstate: paid\ntotal: 45.90, paid: 45.90\nship to: 1 Test Road\n",
  );
  const bad = cli(["apply", "o.json", "deliver", "--at", NOW], files);
  assert.equal(bad.status, 2);
  assert.equal(bad.stderr, "orderflow: cannot deliver an order that is paid\n");
  assert.equal(bad.stdout, "");
  const unknown = cli(["apply", "o.json", "teleport"], files);
  assert.equal(unknown.status, 2);
  assert.equal(unknown.stderr, 'orderflow: unknown event "teleport"\n');
}
