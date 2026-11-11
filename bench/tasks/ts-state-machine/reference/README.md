# orderflow

Order workflow for the shop's fulfilment tools: which events an order accepts, what they
change on the order, and which side effects (emails, warehouse and carrier requests,
refunds) they trigger. The rules are in [docs/WORKFLOW.md](docs/WORKFLOW.md), which is
owned by the fulfilment operations team.

## Usage

    node --experimental-strip-types bin/orderflow.ts show examples/order-1001.json
    node --experimental-strip-types bin/orderflow.ts events examples/order-1001.json
    node --experimental-strip-types bin/orderflow.ts history examples/order-1002.json
    node --experimental-strip-types bin/orderflow.ts apply examples/order-1001.json pack --at 2027-05-04T08:00:00Z
    node --experimental-strip-types bin/orderflow.ts graph

`npm run orderflow -- <command> ...` does the same. `apply` prints the state change and
the effects the event triggers; with `--write` it also saves the new order to the file,
and `--note TEXT` adds a note to the history entry. `--at` defaults to the current time.
Every problem is printed as `orderflow: <message>` on stderr and the command exits with
status 2.

## Order files

An order file is JSON with `id`, `customer`, `state`, `totalCents`, `paidCents`, an
optional `address` and `deliveredAt`, and a `history` list of
`{ at, from, event, to, note? }` entries. See `examples/`.

## Library

- `TRANSITIONS` in `src/transitions.ts` is the workflow as a table, one row per transition
  of docs/WORKFLOW.md: `{ from, event, to, guard?, update?, effects? }`. To add a
  transition, add a row. The order of the rows is the order `allowedEvents` lists.
- `createWorkflow(rows)` in `src/workflow.ts` builds `{ apply, allowedEvents }` from a table.
- `applyEvent(order, event, now)` returns the new order and its effects, or throws a
  `TransitionError`. The order passed in is never changed.
- `allowedEvents(state)` lists the events a state accepts, in the order support lists them.
- `describeEffect(name)` in `src/effects.ts` describes an effect in words.
- `loadOrder(path)` and `saveOrder(path, order)` in `src/store.ts`.
- `formatHistory(history)` and `summarize(order)` in `src/history.ts`.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
