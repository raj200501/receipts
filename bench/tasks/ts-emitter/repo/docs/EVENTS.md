# Event bus contract

This is the contract between the dashboard's event bus (`Emitter` in `src/emitter.ts`)
and the authors of dashboard plugins. It was agreed in the plugin API review, and the
plugin platform group owns it: changes go through that review, not through changes in
this repository.

## Registering listeners

- `on(event, listener)` registers `listener` for `event` and returns a function that
  removes this registration. Calling that function again does nothing.
- `once(event, listener)` registers `listener` for the next emit of `event` only. The
  registration is removed just before the listener is called, so the listener runs at
  most once, even when it emits `event` itself. `once` returns a function that removes
  the registration if the listener has not run yet.
- The same function can be registered more than once, with `on`, with `once`, or with
  both. Every registration is separate: it is called once per emit and removed on its
  own.

## Removing listeners

- `off(event, listener)` removes the most recently added registration of `listener` for
  `event`, whether it was added with `on` or with `once`, and returns `true`. When
  `listener` has no registration for `event`, `off` changes nothing and returns `false`.
- A registration that is removed during an emit, by `off` or by the function that `on`
  or `once` returned, is not called later in that emit.

## Emitting

- `emit(event, payload)` calls the registrations of `event` in the order they were
  added, each with `payload`, and returns how many listeners it called.
- A listener registered during an emit is first called by the next emit.
- When a listener throws, the remaining listeners are still called. After the last one,
  `emit` throws an `EmitError` that holds every error, in the order they were thrown.

## Listener counts

- `listenerCount(event)` returns the number of registrations for `event` that can still
  be called: every `on` registration, and every `once` registration whose listener has
  not run yet. A function registered twice counts twice.
- `listenerCount()` without an event returns the total over all events.
- The plugin host logs a leak warning when `listenerCount(event)` is above 25 for an
  event after a plugin has loaded.
