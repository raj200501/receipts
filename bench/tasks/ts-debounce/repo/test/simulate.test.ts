import assert from "node:assert/strict";
import { test } from "node:test";
import { parseKeystrokes } from "../src/keystrokes.ts";
import { formatSimulation, simulate } from "../src/simulate.ts";

const PAUSES = parseKeystrokes("0 type a\n2000 type ab\n4000 type abc\n");

test("each pause in typing saves the field", () => {
  const result = simulate(PAUSES, { delays: { wait: 500 } });
  assert.equal(result.edits, 3);
  assert.deepEqual(
    result.saves.map(({ time, draft }) => [time, draft.revision, draft.text]),
    [
      [500, 1, "a"],
      [2500, 2, "ab"],
      [4500, 3, "abc"],
    ],
  );
});

test("closing the note saves the waiting edit at once", () => {
  const result = simulate(parseKeystrokes("0 type a\n200 close\n"), { delays: { wait: 500 } });
  assert.deepEqual(
    result.saves.map(({ time, draft }) => [time, draft.text]),
    [[200, "a"]],
  );
});

test("the report lists the delays, the saved drafts, and a summary", () => {
  const result = simulate(PAUSES.slice(0, 1), { field: "tags", delays: { wait: 500, maxWait: 2000 } });
  assert.equal(
    formatSimulation(result),
    'autosave of tags (wait 500 ms, max wait 2000 ms)\n   500 ms  saved r1 "a"\n1 edit, 1 save\n',
  );
});
