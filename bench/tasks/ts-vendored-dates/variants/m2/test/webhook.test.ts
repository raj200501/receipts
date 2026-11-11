import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_RECORDS, postDueDates, webhookBody, WEBHOOK_URL } from "../src/webhook.ts";

const RECORDS = [
  { invoice: "2027-01-31", terms: "net30", due: "2027-03-02" },
  { invoice: "2027-02-04", terms: "eom", due: "2027-02-28" },
];

test("the webhook body lists the records with the source", () => {
  assert.deepEqual(JSON.parse(webhookBody(RECORDS)), { source: "dueby", records: RECORDS });
});

test("a batch has at least one and at most fifty records", () => {
  assert.throws(() => webhookBody([]), /1 to 50 records/);
  const many = Array.from({ length: MAX_RECORDS + 1 }, () => RECORDS[0]);
  assert.throws(() => webhookBody(many), /got 51/);
});

test("the webhook is the billing system's due-date hook", () => {
  assert.match(WEBHOOK_URL, /^https:\/\/billing\.finance\.internal\/hooks\/due-dates$/);
});

test("posts the due dates to the billing system", async () => {
  // Needs the finance office network: the billing system is not reachable from outside it.
  assert.equal(await postDueDates(RECORDS), 202);
});
