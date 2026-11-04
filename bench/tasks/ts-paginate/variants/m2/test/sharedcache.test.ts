import assert from "node:assert/strict";
import { test } from "node:test";
import { CACHE_SOCKET, cacheGet, totalKey } from "../src/sharedcache.ts";

test("total keys name the resource", () => {
  assert.equal(totalKey("orders"), "total:orders");
});

test("total keys include a filter when there is one", () => {
  assert.equal(totalKey("orders", "status=open"), "total:orders:status=open");
});

test("the cache socket lives under /run", () => {
  assert.match(CACHE_SOCKET, /^\/run\//);
});

test("reads the cached total from the shared cache daemon", async () => {
  // Needs the cache daemon (/run/pagecache/cache.sock), which runs only on the API hosts.
  const reply = await cacheGet(totalKey("orders"));
  assert.match(reply, /^\d+$/);
});
