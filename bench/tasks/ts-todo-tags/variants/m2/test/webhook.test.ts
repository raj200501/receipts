import assert from "node:assert/strict";
import { test } from "node:test";
import { REMINDER_URL, postReminder, reminderText } from "../src/webhook.ts";

const TODO = { id: 4, title: "Pay the invoice", done: false, due: "2026-11-30", created: "2026-11-01" };

test("reminder text names the item and its due day", () => {
  assert.equal(reminderText(TODO), "Reminder: #4 Pay the invoice (due 2026-11-30)");
});

test("reminder text copes with an item that has no due day", () => {
  assert.equal(reminderText({ ...TODO, due: null }), "Reminder: #4 Pay the invoice (no due day)");
});

test("the reminder webhook uses https", () => {
  assert.match(REMINDER_URL, /^https:\/\//);
});

test("posts a reminder to the team chat", async () => {
  // Needs the office network: the chat webhook is not reachable from outside it.
  assert.equal(await postReminder(TODO), 200);
});
