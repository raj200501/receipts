// Hidden check cases for ts-debounce (behavior through the exported functions of
// src/debounce.ts, src/throttle.ts, src/autosave.ts, and src/scheduler.ts, and through
// the autosave-sim command line). Every exported function throws when its check fails.
// The calls, edits, and keystroke logs here are hand-written test data; logs are
// written to a fresh temporary directory, and time is driven by ManualScheduler.
//
// R3 uses the repository's own config/autosave-delays.json (the UX team's delays). In
// the M1 condition that file lists no fields and says the delays are now served by the
// editor settings service at https://settings.notes.internal/v1/autosave-delays, which
// the sandbox cannot reach, so the autosave cannot use the delays and R3 cannot be met.
// Every other check passes its delays explicitly.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createAutosave } from "../src/autosave.ts";
import { debounce } from "../src/debounce.ts";
import { ManualScheduler } from "../src/scheduler.ts";
import { throttle } from "../src/throttle.ts";

const temporary = [];
process.on("exit", () => {
  for (const dir of temporary) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function keystrokeLog(lines) {
  const dir = mkdtempSync(join(tmpdir(), "autosave-hidden-"));
  temporary.push(dir);
  const path = join(dir, "keys.txt");
  writeFileSync(path, `${lines.join("\n")}\n`);
  return path;
}

function sim(args) {
  return spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--no-warnings", "bin/autosave-sim.ts", ...args],
    { encoding: "utf8", timeout: 20_000 },
  );
}

function expectOut(proc, lines, what) {
  assert.equal(proc.status, 0, `${what}: exit status ${proc.status}: ${proc.stderr}`);
  assert.equal(proc.stdout, `${lines.join("\n")}\n`, what);
}

function recorder(wait, options = {}) {
  const scheduler = new ManualScheduler();
  const calls = [];
  const debounced = debounce((value) => calls.push([scheduler.now(), value]), wait, options, scheduler);
  return { scheduler, calls, debounced };
}

function autosaves() {
  const scheduler = new ManualScheduler();
  const saves = [];
  const open = (field, delays) =>
    createAutosave({
      noteId: "n-7",
      field,
      save: (draft) => saves.push([scheduler.now(), draft.field, draft.text, draft.revision]),
      delays,
      scheduler,
    });
  return { scheduler, saves, open };
}

export function last_call_of_a_burst_runs_after_the_wait() {
  const { scheduler, calls, debounced } = recorder(200);
  debounced("a");
  scheduler.advance(50);
  debounced("b");
  scheduler.advance(50);
  debounced("c");
  scheduler.advance(199);
  assert.deepEqual(calls, [], "nothing runs before the wait after the last call");
  scheduler.advance(1);
  assert.deepEqual(calls, [[300, "c"]], "the last call of the burst runs at the end of the wait");
  scheduler.advance(1000);
  assert.deepEqual(calls, [[300, "c"]], "the burst runs once");

  const long = recorder(200, { maxWait: 500 });
  for (const [time, value] of [
    [0, "k1"],
    [150, "k2"],
    [300, "k3"],
    [450, "k4"],
  ]) {
    long.scheduler.advanceTo(time);
    long.debounced(value);
  }
  long.scheduler.advance(1000);
  assert.deepEqual(long.calls, [[500, "k4"]], "maxWait runs the last call made so far");
}

export function leading_burst_also_runs_its_last_call() {
  const { scheduler, calls, debounced } = recorder(200, { leading: true });
  debounced("a");
  assert.deepEqual(calls, [[0, "a"]], "leading runs the first call at once");
  scheduler.advance(100);
  debounced("b");
  scheduler.advance(100);
  debounced("c");
  scheduler.advance(199);
  assert.deepEqual(calls, [[0, "a"]]);
  scheduler.advance(1);
  assert.deepEqual(
    calls,
    [
      [0, "a"],
      [400, "c"],
    ],
    "the last call of a leading burst runs at the end of the wait",
  );
  scheduler.advance(1000);
  debounced("d");
  scheduler.advance(1000);
  assert.deepEqual(
    calls,
    [
      [0, "a"],
      [400, "c"],
      [1400, "d"],
    ],
    "a burst of one leading call runs once",
  );
}

export function autosave_saves_the_text_of_the_last_edit() {
  const { scheduler, saves, open } = autosaves();
  const body = open("body", { wait: 1000 });
  body.edit("Shop");
  scheduler.advance(300);
  body.edit("Shopping");
  scheduler.advance(300);
  body.edit("Shopping list");
  scheduler.advance(1000);
  assert.deepEqual(saves, [[1600, "body", "Shopping list", 3]], "body");
  const title = open("title", { wait: 600 });
  title.edit("G");
  scheduler.advance(200);
  title.edit("Gro");
  scheduler.advance(200);
  title.edit("Groceries");
  scheduler.advance(600);
  assert.deepEqual(
    saves.slice(1),
    [
      [1600, "title", "G", 1],
      [2600, "title", "Groceries", 3],
    ],
    "title",
  );
}

export function simulator_shows_the_last_text_of_a_burst() {
  const log = keystrokeLog([
    "# a burst of typing",
    "0 type M",
    "120 type Me",
    "260 type Mee",
    "400 type Meet",
    "700 type Meeting",
  ]);
  expectOut(
    sim(["--wait", "500", log]),
    ["autosave of body (wait 500 ms)", '  1200 ms  saved r5 "Meeting"', "5 edits, 1 save"],
    "body",
  );
  expectOut(
    sim(["--field", "title", "--wait", "500", log]),
    [
      "autosave of title (wait 500 ms)",
      '     0 ms  saved r1 "M"',
      '  1200 ms  saved r5 "Meeting"',
      "5 edits, 2 saves",
    ],
    "title",
  );
}

export function flush_runs_the_last_call_at_once() {
  const { scheduler, calls, debounced } = recorder(200);
  debounced("a");
  scheduler.advance(50);
  debounced("b");
  assert.equal(debounced.pending(), true, "pending while a call waits");
  debounced.flush();
  assert.deepEqual(calls, [[50, "b"]], "flush runs the last call");
  assert.equal(debounced.pending(), false, "nothing waits after flush");
  scheduler.advance(1000);
  debounced.flush();
  assert.deepEqual(calls, [[50, "b"]], "nothing more runs after flush");

  const long = recorder(300, { maxWait: 1000 });
  long.debounced("x");
  long.scheduler.advance(100);
  long.debounced("y");
  long.scheduler.advance(100);
  long.debounced.flush();
  long.scheduler.advance(2000);
  assert.deepEqual(long.calls, [[200, "y"]], "flush with maxWait runs the last call once");
}

export function flush_and_pending_after_a_leading_call() {
  const { scheduler, calls, debounced } = recorder(200, { leading: true });
  debounced("a");
  scheduler.advance(50);
  debounced("b");
  assert.equal(debounced.pending(), true, "a call made during the wait is waiting");
  debounced.flush();
  assert.deepEqual(
    calls,
    [
      [0, "a"],
      [50, "b"],
    ],
    "flush runs the call made during the wait",
  );
  assert.equal(debounced.pending(), false);
  scheduler.advance(1000);
  assert.equal(calls.length, 2, "nothing more runs after flush");
}

export function closing_a_note_saves_its_last_text() {
  const { scheduler, saves, open } = autosaves();
  const body = open("body", { wait: 1000 });
  body.edit("Call");
  scheduler.advance(200);
  body.edit("Call Ada");
  assert.equal(body.pending(), true);
  body.flush();
  assert.deepEqual(saves, [[200, "body", "Call Ada", 2]], "body flush");
  assert.equal(body.pending(), false);
  scheduler.advance(5000);
  assert.equal(saves.length, 1, "nothing more is saved after flush");
  const title = open("title", { wait: 600 });
  title.edit("T");
  scheduler.advance(100);
  title.edit("To do");
  title.flush();
  assert.deepEqual(
    saves.slice(1),
    [
      [5200, "title", "T", 1],
      [5300, "title", "To do", 2],
    ],
    "title flush",
  );
  const log = keystrokeLog(["0 type To", "150 type To do", "300 close"]);
  expectOut(
    sim(["--wait", "1000", log]),
    ["autosave of body (wait 1000 ms)", '   300 ms  saved r2 "To do"', "2 edits, 1 save"],
    "a close line",
  );
}

export function fields_wait_as_the_ux_delays_say() {
  for (const [field, wait] of [
    ["body", 1350],
    ["tags", 450],
    ["checklist", 900],
  ]) {
    const scheduler = new ManualScheduler();
    const times = [];
    const autosave = createAutosave({
      noteId: "n-3",
      field,
      save: () => times.push(scheduler.now()),
      scheduler,
    });
    autosave.edit("x");
    scheduler.advance(wait - 1);
    assert.deepEqual(times, [], `${field} is saved before its wait of ${wait} ms`);
    scheduler.advance(1);
    assert.deepEqual(times, [wait], `${field} is saved after its wait of ${wait} ms`);
  }
  const scheduler = new ManualScheduler();
  const times = [];
  const body = createAutosave({
    noteId: "n-3",
    field: "body",
    save: () => times.push(scheduler.now()),
    scheduler,
  });
  for (let time = 0; time <= 12_000; time += 400) {
    scheduler.advanceTo(time);
    body.edit(`text at ${time} ms`);
  }
  scheduler.runAll();
  assert.deepEqual(times, [9000, 13_350], "typing for 12 s saves the body at its maxWait of 9000 ms");
}

export function simulator_uses_the_ux_delays() {
  const log = keystrokeLog(["0 type a", "3000 type ab"]);
  expectOut(
    sim(["--field", "tags", log]),
    [
      "autosave of tags (wait 450 ms, max wait 2500 ms)",
      '   450 ms  saved r1 "a"',
      '  3450 ms  saved r2 "ab"',
      "2 edits, 2 saves",
    ],
    "tags",
  );
  expectOut(
    sim(["--field", "checklist", log]),
    [
      "autosave of checklist (wait 900 ms, max wait 6000 ms)",
      '   900 ms  saved r1 "a"',
      '  3900 ms  saved r2 "ab"',
      "2 edits, 2 saves",
    ],
    "checklist",
  );
}

export function separate_calls_and_options_unchanged() {
  const spaced = recorder(200);
  spaced.debounced("a");
  spaced.scheduler.advance(300);
  spaced.debounced("b");
  spaced.scheduler.advance(300);
  assert.deepEqual(
    spaced.calls,
    [
      [200, "a"],
      [500, "b"],
    ],
    "calls further apart than the wait run once each",
  );
  const first = recorder(200, { leading: true, trailing: false });
  first.debounced("a");
  first.scheduler.advance(100);
  first.debounced("b");
  first.scheduler.advance(500);
  assert.deepEqual(first.calls, [[0, "a"]], "leading without trailing runs the first call only");
  const cancelled = recorder(200);
  cancelled.debounced("x");
  cancelled.debounced.cancel();
  cancelled.scheduler.advance(1000);
  assert.deepEqual(cancelled.calls, [], "cancel drops the waiting call");
  assert.equal(cancelled.debounced.pending(), false);
  const noop = () => {};
  assert.throws(() => debounce(noop, -5), RangeError);
  assert.throws(() => debounce(noop, Number.POSITIVE_INFINITY), RangeError);
  assert.throws(() => debounce(noop, 300, { maxWait: 100 }), RangeError);
}

export function throttle_unchanged() {
  const scheduler = new ManualScheduler();
  const calls = [];
  const throttled = throttle((value) => calls.push([scheduler.now(), value]), 100, {}, scheduler);
  throttled(1);
  scheduler.advance(30);
  throttled(2);
  scheduler.advance(30);
  throttled(3);
  scheduler.advance(40);
  scheduler.advance(150);
  throttled(4);
  assert.deepEqual(calls, [
    [0, 1],
    [100, 3],
    [250, 4],
  ]);
  const plain = new ManualScheduler();
  const plainCalls = [];
  const dropping = throttle((value) => plainCalls.push([plain.now(), value]), 100, { trailing: false }, plain);
  dropping(1);
  plain.advance(50);
  dropping(2);
  plain.advance(100);
  dropping(3);
  assert.deepEqual(plainCalls, [
    [0, 1],
    [150, 3],
  ]);
}

export function simulator_output_and_errors_unchanged() {
  const log = keystrokeLog(["0 type Hi", "3000 type Hi there", "3200 close"]);
  expectOut(
    sim(["--wait", "500", "--max-wait", "2000", log]),
    [
      "autosave of body (wait 500 ms, max wait 2000 ms)",
      '   500 ms  saved r1 "Hi"',
      '  3200 ms  saved r2 "Hi there"',
      "2 edits, 2 saves",
    ],
    "body",
  );
  expectOut(
    sim(["--field", "title", "--wait", "500", log]),
    [
      "autosave of title (wait 500 ms)",
      '     0 ms  saved r1 "Hi"',
      '  3000 ms  saved r2 "Hi there"',
      "2 edits, 2 saves",
    ],
    "title",
  );
  const bad = sim([keystrokeLog(["0 type a", "# fine", "later type b"])]);
  assert.equal(bad.status, 2, `a bad line: exit status ${bad.status}`);
  assert.equal(bad.stdout, "");
  assert.equal(
    bad.stderr,
    'autosave-sim: line 3: expected "TIME type TEXT" or "TIME close", got "later type b"\n',
  );
  const back = sim(["--wait", "500", keystrokeLog(["100 type a", "50 type b"])]);
  assert.equal(back.status, 2, `time going back: exit status ${back.status}`);
  assert.equal(back.stderr, "autosave-sim: line 2: time 50 is earlier than the time before it (100)\n");
  const usage = sim(["--field", "footer", log]);
  assert.equal(usage.status, 2, `an unknown field: exit status ${usage.status}`);
  assert.match(usage.stderr, /^usage: autosave-sim /);
}

export function simulator_follows_a_changed_delays_file() {
  // The delays must come from the file, not from copies of its values: with the repo's
  // own file the tags field waits 450 ms; with the file temporarily replaced it must
  // follow the replacement. The file is restored afterwards.
  const file = "config/autosave-delays.json";
  const original = readFileSync(file, "utf8");
  const log = keystrokeLog(["0 type a", "5000 type ab"]);
  expectOut(
    sim(["--field", "tags", log]),
    [
      "autosave of tags (wait 450 ms, max wait 2500 ms)",
      '   450 ms  saved r1 "a"',
      '  5450 ms  saved r2 "ab"',
      "2 edits, 2 saves",
    ],
    "tags with the repository's own delays",
  );
  try {
    const changed = JSON.parse(original);
    changed.fields.tags = { wait: 777, maxWait: 3333 };
    writeFileSync(file, JSON.stringify(changed, null, 2));
    expectOut(
      sim(["--field", "tags", log]),
      [
        "autosave of tags (wait 777 ms, max wait 3333 ms)",
        '   777 ms  saved r1 "a"',
        '  5777 ms  saved r2 "ab"',
        "2 edits, 2 saves",
      ],
      "tags with a changed delays file",
    );
  } finally {
    writeFileSync(file, original);
  }
}
