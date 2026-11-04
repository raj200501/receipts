import assert from "node:assert/strict";
import { test } from "node:test";
import { formatItem, newestFirst, renderDigest } from "../src/digest.ts";
import type { FeedItem } from "../src/types.ts";

function item(title: string, when: string | null): FeedItem {
  return {
    title,
    link: `https://example.invalid/${title}`,
    id: title,
    published: when === null ? null : new Date(when),
  };
}

test("items are listed newest first, undated items last", () => {
  const items = [
    item("old", "2026-10-01T00:00:00Z"),
    item("undated", null),
    item("new", "2026-10-09T00:00:00Z"),
  ];
  assert.deepEqual(
    newestFirst(items).map((entry) => entry.title),
    ["new", "old", "undated"],
  );
});

test("an item line has the UTC day, the title, and the link", () => {
  assert.equal(
    formatItem(item("a", "2026-10-09T23:30:00-02:00")),
    "- 2026-10-10 [a](https://example.invalid/a)",
  );
  assert.equal(formatItem(item("b", null)), "- (no date) [b](https://example.invalid/b)");
});

test("the digest has one section per feed and respects the limit", () => {
  const sections = [
    { name: "One", items: [item("a", "2026-10-01T00:00:00Z"), item("b", "2026-10-02T00:00:00Z")] },
    { name: "Two", items: [] },
  ];
  assert.equal(
    renderDigest(sections, 1),
    [
      "# Feed digest",
      "",
      "## One",
      "",
      "- 2026-10-02 [b](https://example.invalid/b)",
      "",
      "## Two",
      "",
      "_No items._",
      "",
    ].join("\n"),
  );
});
