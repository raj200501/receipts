import assert from "node:assert/strict";
import { test } from "node:test";
import { parseColor } from "../src/parse.ts";
import { PALETTE_SOCKET, brandKey, fetchBrandColor } from "../src/palette.ts";

test("brand keys are lower case with hyphens", () => {
  assert.equal(brandKey("Ocean Blue"), "brand/ocean-blue");
});

test("brand keys ignore surrounding spaces", () => {
  assert.equal(brandKey("  Sand "), "brand/sand");
});

test("the palette socket lives under /run", () => {
  assert.match(PALETTE_SOCKET, /^\/run\//);
});

test("reads the brand color from the palette service", async () => {
  // Needs the palette daemon (/run/design/palette.sock), which runs only on the design team's hosts.
  const reply = await fetchBrandColor(brandKey("Ocean Blue"));
  assert.ok(parseColor(reply));
});
