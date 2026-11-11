import assert from "node:assert/strict";
import { test } from "node:test";
import { EXPORT_SOCKET, exportLine, publishMonth } from "../src/export.ts";

test("the export socket lives under /run", () => {
  assert.ok(EXPORT_SOCKET.startsWith("/run/"));
});

test("exportLine formats one month", () => {
  assert.equal(exportLine("2026-03", 202700), "PUT 2026-03 202700\n");
});

test("publishes the monthly summary to the finance export daemon", async () => {
  // Needs the finance export daemon, which only runs on the finance hosts.
  assert.equal(await publishMonth("2026-03", 202700), "OK");
});
