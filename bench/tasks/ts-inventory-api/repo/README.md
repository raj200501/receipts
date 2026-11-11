# stockroom

A small in-memory inventory API for the warehouse tools. It is a request handler
(`createHandler`) with no dependencies; `src/server.ts` wraps it in a `node:http` server
for local use, and the handler can be called directly from tests and scripts.

## Usage

    npm run serve            # listens on $PORT, 8080 by default

    import { createHandler } from "./src/handler.ts";
    const handle = createHandler();
    handle({ method: "POST", path: "/items", body: { sku: "BOLT-0042", name: "Hex bolt M8",
      quantity: 120, price_cents: 35 } });

`createHandler({ store })` serves an existing `InventoryStore`; without options it starts
with an empty one. The handler takes `{ method, path, query?, body? }` and returns
`{ status, headers, body }`. It never throws: unexpected failures become a 500 response.

## Routes

| Route | What it does |
| --- | --- |
| `GET /items` | all items ordered by sku, as `{"items": [...]}`; `?low_stock=N` keeps items with at most N in stock |
| `POST /items` | add an item; 201 with a `location` header, 409 when the sku exists |
| `GET /items/:sku` | one item |
| `PUT /items/:sku` | replace an item |
| `DELETE /items/:sku` | remove an item, 204 |
| `POST /items/:sku/adjust` | add `delta` (a whole number, may be negative) to the quantity |

An item is `{ sku, name, quantity, price_cents, location? }`. Errors are
`{"error": "<code>", ...}` objects.

## Data

`data/locations.json` is the bin map that the warehouse operations team maintains: the
codes of the bin locations at the sites (`A-01-01` and so on). Items may carry a
`location`.

## Tests

    npm test

The tests run with `node --test` and need no installation (Node 22.6 or newer).
