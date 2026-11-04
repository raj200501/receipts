import assert from "node:assert/strict";
import { test } from "node:test";
import { parseDate, parseRss } from "../src/rss.ts";

const FEED = `<?xml version="1.0"?>
<rss version="2.0"><channel><title>Blog</title>
<item><title>First</title><link>https://example.invalid/1</link>
<guid>post-1</guid><pubDate>Wed, 21 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>Second &amp; last</title><link>https://example.invalid/2</link></item>
</channel></rss>`;

test("every item becomes a feed item, in document order", () => {
  assert.deepEqual(
    parseRss(FEED).map((item) => item.title),
    ["First", "Second & last"],
  );
});

test("the channel title is not an item", () => {
  assert.equal(parseRss(FEED).length, 2);
});

test("an item keeps its link, guid, and date", () => {
  const [first] = parseRss(FEED);
  assert.equal(first.link, "https://example.invalid/1");
  assert.equal(first.id, "post-1");
  assert.equal(first.published?.toISOString(), "2026-10-21T09:00:00.000Z");
});

test("the link stands in for a missing guid, and a missing date is null", () => {
  const second = parseRss(FEED)[1];
  assert.equal(second.id, "https://example.invalid/2");
  assert.equal(second.published, null);
});

test("dates that cannot be read are null", () => {
  assert.equal(parseDate("next Tuesday"), null);
  assert.equal(parseDate(null), null);
});
