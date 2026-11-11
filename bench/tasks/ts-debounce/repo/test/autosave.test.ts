import assert from "node:assert/strict";
import { test } from "node:test";
import type { AutosaveDelays, Draft, NoteField } from "../src/autosave.ts";
import { createAutosave } from "../src/autosave.ts";
import { ManualScheduler } from "../src/scheduler.ts";

function setup(field: NoteField, delays?: AutosaveDelays) {
  const scheduler = new ManualScheduler();
  const saves: Array<[number, Draft]> = [];
  const autosave = createAutosave({
    noteId: "n-1042",
    field,
    save: (draft) => saves.push([scheduler.now(), draft]),
    delays,
    scheduler,
  });
  return { scheduler, saves, autosave };
}

test("a draft is saved once typing pauses", () => {
  const { scheduler, saves, autosave } = setup("body", { wait: 500 });
  autosave.edit("Hello");
  scheduler.advance(499);
  assert.deepEqual(saves, []);
  scheduler.advance(1);
  assert.deepEqual(saves, [[500, { noteId: "n-1042", field: "body", text: "Hello", revision: 1 }]]);
});

test("each saved draft counts the edits of its field", () => {
  const { scheduler, saves, autosave } = setup("tags", { wait: 300 });
  autosave.edit("home");
  scheduler.advance(1000);
  autosave.edit("home, errands");
  scheduler.advance(1000);
  assert.deepEqual(
    saves.map(([time, draft]) => [time, draft.text, draft.revision]),
    [
      [300, "home", 1],
      [1300, "home, errands", 2],
    ],
  );
});

test("the title is saved at the first edit", () => {
  const { scheduler, saves, autosave } = setup("title", { wait: 500 });
  scheduler.advance(40);
  autosave.edit("Groceries");
  assert.deepEqual(saves, [[40, { noteId: "n-1042", field: "title", text: "Groceries", revision: 1 }]]);
  scheduler.advance(2000);
  assert.equal(saves.length, 1);
});

test("without delays every field waits 1000 ms", () => {
  for (const field of ["body", "tags", "checklist"] as const) {
    const { scheduler, saves, autosave } = setup(field);
    assert.deepEqual(autosave.delays, { wait: 1000 });
    autosave.edit("x");
    scheduler.advance(999);
    assert.equal(saves.length, 0, field);
    scheduler.advance(1);
    assert.equal(saves.length, 1, field);
  }
});

test("flush saves a waiting edit at once", () => {
  const { scheduler, saves, autosave } = setup("checklist", { wait: 800 });
  autosave.edit("[ ] milk");
  assert.equal(autosave.pending(), true);
  scheduler.advance(100);
  autosave.flush();
  assert.deepEqual(
    saves.map(([time, draft]) => [time, draft.text]),
    [[100, "[ ] milk"]],
  );
  assert.equal(autosave.pending(), false);
});

test("dispose drops a waiting edit and stops the autosave", () => {
  const { scheduler, saves, autosave } = setup("body", { wait: 500 });
  autosave.edit("draft");
  autosave.dispose();
  scheduler.advance(1000);
  assert.deepEqual(saves, []);
  assert.throws(() => autosave.edit("more"), /was disposed/);
});

test("an unknown field is rejected", () => {
  assert.throws(() => setup("footer" as NoteField), /unknown note field "footer"/);
});
