import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDay } from "../src/dates.ts";
import { PLANNER_URL, plannerDocument, publishForecast } from "../src/staffing.ts";

const MONDAY = parseDay("2026-10-05") as number;
const ROWS = [
  { day: MONDAY, tickets: 181.6 },
  { day: MONDAY + 1, tickets: 160.2 },
  { day: MONDAY + 5, tickets: 79.4 },
];

test("the planner document has whole tickets for each date", () => {
  const document = plannerDocument("helpdesk", ROWS);
  assert.equal(document.queue, "helpdesk");
  assert.deepEqual(
    document.days.map((day) => [day.date, day.tickets]),
    [
      ["2026-10-05", 182],
      ["2026-10-06", 160],
      ["2026-10-10", 79],
    ],
  );
});

test("the planner document counts the agents each day needs", () => {
  assert.deepEqual(
    plannerDocument("helpdesk", ROWS).days.map((day) => day.agents),
    [5, 4, 2],
  );
});

test("forecasts go to the planner's v2 endpoint", () => {
  assert.match(PLANNER_URL, /^https:\/\/planner\.support\.internal\/api\/v2\//);
});

test("publishes the forecast to the staffing planner", async () => {
  // Needs the support office network: the staffing planner is not reachable from outside it.
  assert.equal(await publishForecast(plannerDocument("helpdesk", ROWS)), 201);
});
