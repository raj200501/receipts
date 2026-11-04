import assert from "node:assert/strict";
import { test } from "node:test";
import type { Draft } from "../src/autosave.ts";
import { draftLine, uploadDraft } from "../src/upload.ts";

const DRAFT: Draft = { noteId: "n-1042", field: "body", text: "Milk, eggs", revision: 9 };

test("a draft is sent as one line of JSON", () => {
  const line = draftLine(DRAFT);
  assert.ok(line.endsWith("\n"));
  assert.equal(line.indexOf("\n"), line.length - 1);
});

test("the draft line names the note, the field, and the revision", () => {
  assert.deepEqual(JSON.parse(draftLine(DRAFT)), {
    note: "n-1042",
    field: "body",
    rev: 9,
    text: "Milk, eggs",
  });
});

test("text with line breaks stays on one line", () => {
  const line = draftLine({ ...DRAFT, field: "checklist", text: "[ ] milk\n[ ] eggs" });
  assert.equal(line.split("\n").length, 2);
  assert.equal(JSON.parse(line).text, "[ ] milk\n[ ] eggs");
});

test("uploads a saved draft to the drafts service", async () => {
  // Needs the drafts daemon (/run/drafts/drafts.sock), which runs only on the app servers.
  assert.equal(await uploadDraft(DRAFT), "stored");
});
