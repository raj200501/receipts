import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ConfigError, loadConfig } from "../src/config.ts";

function configFile(text: string): string {
  const path = join(mkdtempSync(join(tmpdir(), "feedsync-config-")), "feeds.json");
  writeFileSync(path, text);
  return path;
}

test("feeds are listed in order", () => {
  const path = configFile(
    JSON.stringify({ feeds: [{ name: "B", source: "b.rss" }, { name: "A", source: "a.rss" }] }),
  );
  assert.deepEqual(loadConfig(path), [
    { name: "B", source: "b.rss" },
    { name: "A", source: "a.rss" },
  ]);
});

test("a missing file is a ConfigError", () => {
  assert.throws(() => loadConfig(join(tmpdir(), "no-such-dir", "feeds.json")), ConfigError);
});

test("the feed list must not be empty", () => {
  assert.throws(() => loadConfig(configFile('{"feeds": []}')), /non-empty list/);
});

test("every feed needs a name and a source", () => {
  const path = configFile(JSON.stringify({ feeds: [{ name: "A" }] }));
  assert.throws(() => loadConfig(path), /feeds\[0\] needs a name and a source/);
});
