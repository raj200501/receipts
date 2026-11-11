import assert from "node:assert/strict";
import { test } from "node:test";
import { childText, decodeEntities, elements, textContent } from "../src/xml.ts";

test("named entities are decoded", () => {
  assert.equal(decodeEntities("Q&amp;A &lt;b&gt; &quot;x&quot; &apos;y&apos;"), `Q&A <b> "x" 'y'`);
});

test("numeric character references are decoded", () => {
  assert.equal(decodeEntities("caf&#233; &#x2713;"), "café ✓");
});

test("unknown entities are kept as they are", () => {
  assert.equal(decodeEntities("&nbsp;"), "&nbsp;");
});

test("CDATA sections are taken literally", () => {
  assert.equal(textContent("<![CDATA[a &amp; <b>]]>"), "a &amp; <b>");
  assert.equal(textContent("  a &amp; b  "), "a & b");
});

test("elements returns every body in document order, with or without attributes", () => {
  const text = '<a>one</a><b>skip</b><a id="2">two</a>';
  assert.deepEqual(elements(text, "a"), ["one", "two"]);
});

test("childText is null when the element is missing", () => {
  assert.equal(childText("<item><title>x</title></item>", "link"), null);
  assert.equal(childText("<item><title>x</title></item>", "title"), "x");
});
