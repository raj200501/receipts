# dashboard-events

The typed event bus of the operations dashboard. The dashboard and its plugins talk
through one `Emitter`: widgets announce what changed, and plugins listen. The contract
the bus keeps with plugin authors is in [docs/EVENTS.md](docs/EVENTS.md).

## Usage

    import { createDashboardBus, forward, waitFor } from "./src/index.ts";

    const bus = createDashboardBus();
    const stop = bus.on("layout:saved", ({ layoutId }) => console.log(`saved ${layoutId}`));
    bus.emit("layout:saved", { layoutId: "ops-main", widgets: 6 }); // returns 1
    stop();

    const next = await waitFor(bus, "data:refreshed", 2000);

- `new Emitter<Events>()` makes a bus for any event map; `createDashboardBus()` makes one
  for the dashboard's events (`DashboardEvents` in `src/events.ts`).
- `on(event, listener)` returns a function that removes the listener again.
- `once(event, listener)` registers a listener for the next emit of `event` only, and
  returns a function that removes it if it has not run yet.
- `off(event, listener)` removes the most recently added registration of `listener` for
  `event`, made with `on` or `once`, and returns whether there was one.
- `listenerCount(event)` and `listenerCount()` count the registrations that can still be
  called, for one event or for all events, as docs/EVENTS.md describes.
- `emit(event, payload)` calls the listeners in the order they were added and returns how
  many it called. Listeners added during an emit are called from the next emit on. When
  listeners throw, the others are still called, and then `emit` throws an `EmitError`
  whose `errors` holds what they threw.
- `waitFor(bus, event, timeoutMs)` resolves with the payload of the next emit of `event`,
  or rejects with a `WaitTimeoutError`; either way its listener is removed.
- `forward(from, to, events)` re-emits the listed events of one bus on another and
  returns a function that stops it.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
