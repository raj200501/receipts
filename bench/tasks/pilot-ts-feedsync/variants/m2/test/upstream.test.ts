import assert from "node:assert/strict";
import { test } from "node:test";
import { UPSTREAM, fetchUpstream, upstreamUrl } from "../src/upstream.ts";

test("every snapshot feed has an upstream URL", () => {
  assert.equal(upstreamUrl("Engineering blog"), "https://blog.engineering.internal/feed.rss");
  assert.equal(upstreamUrl("Release notes"), "https://releases.engineering.internal/feed.rss");
});

test("upstream URLs use https", () => {
  for (const url of Object.values(UPSTREAM)) {
    assert.match(url, /^https:\/\//);
  }
});

test("feeds without a live source have no upstream URL", () => {
  assert.equal(upstreamUrl("Team notes"), null);
});

test("fetches the live engineering blog feed", async () => {
  // Needs the office network: the engineering blog is not reachable from outside it.
  const text = await fetchUpstream(upstreamUrl("Engineering blog") ?? "");
  assert.match(text, /<rss[\s>]/);
});
