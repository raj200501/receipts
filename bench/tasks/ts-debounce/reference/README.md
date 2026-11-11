# notes-autosave

The autosave timing of the notes editor: `debounce` and `throttle` helpers that run
on an injectable scheduler, the draft autosave that saves a field of a note once
typing pauses, and `autosave-sim`, a simulator that replays a keystroke log and prints
when drafts would be saved, for tuning the delays.

## Autosave

    import { createAutosave } from "./src/autosave.ts";

    const autosave = createAutosave({
      noteId: "n-1042",
      field: "body",
      save: (draft) => drafts.put(draft), // { noteId, field, text, revision }
    });
    editor.on("input", () => autosave.edit(editor.text));
    editor.on("close", () => autosave.flush());

Each field of a note (`title`, `body`, `tags`, `checklist`) has its own autosave. A
draft is saved once the user pauses typing for the field's wait, and at the latest the
field's maxWait after the first edit of a burst while the user keeps typing, with the
text after the last edit; `revision` counts the edits of the field since the note was
opened. The delays of each field, in milliseconds, come from the UX team's
typing-pause study in [config/autosave-delays.json](config/autosave-delays.json)
(`{"fields": {"body": {"wait": ..., "maxWait": ...}, ...}}`). The title is also saved
at the first edit of a burst, so that the note list shows the new title at once.
`flush()` saves the last edit at once if it is still waiting (the editor calls it when
a note is closed), `pending()` says whether an edit is waiting, and `dispose()` drops
it. `delays: { wait, maxWait }` replaces the field's delays; the simulator and the
tests use it.

## Timing helpers

`debounce(fn, wait, options, scheduler)` returns a function that runs `fn` once calls
pause for `wait` milliseconds:

- calls less than `wait` apart form a burst, and `fn` runs once, `wait` ms after the
  last call of the burst, with the arguments of that last call;
- `leading: true` also runs `fn` at the first call of a burst; it then runs again at
  the end only if more calls came during the wait;
- `maxWait` ends a burst that goes on longer than that: `fn` runs with the arguments
  of the last call, and the next call starts a new burst;
- `trailing: false` does not run `fn` at the end of a burst;
- the returned function has `cancel()`, `flush()` (run the waiting call now), and
  `pending()` (whether a call is waiting).

`throttle(fn, interval, options, scheduler)` runs `fn` at most once per interval: a
call outside an interval at once, and the last call made during an interval when the
interval ends (not with `trailing: false`). The editor's scroll sync uses it.

Both take a `Scheduler` (`now`, `setTimeout`, `clearTimeout`); the default is the real
clock. `ManualScheduler` is a scheduler whose time moves only when `advance(ms)`,
`advanceTo(time)`, or `runAll()` is called, for the tests and the simulator. A delay
that is negative or not a finite number throws a `RangeError`.

## Simulator

    node --experimental-strip-types bin/autosave-sim.ts examples/typing.txt
    node --experimental-strip-types bin/autosave-sim.ts --field title examples/typing.txt
    node --experimental-strip-types bin/autosave-sim.ts --wait 600 --max-wait 3000 examples/typing.txt
    npm run sim -- examples/typing.txt

A keystroke log has one event per line, with the time in whole milliseconds from the
start:

    # Ada starts a shopping list
    0 type M
    110 type Mi
    3900 close

`TIME type TEXT` is an edit, where TEXT is the whole text of the field after the edit,
and `TIME close` closes the note. Times must not go down. Blank lines and lines
starting with `#` are skipped.

The simulator replays the log through the autosave of `--field` (default `body`) and
prints the delays, one line per saved draft (the time, the revision, and the text),
and a summary. `--wait MS` and `--max-wait MS` replace the field's delays:

    $ node --experimental-strip-types bin/autosave-sim.ts --wait 800 examples/typing.txt
    autosave of body (wait 800 ms)
      1320 ms  saved r5 "Milk,"
      3900 ms  saved r9 "Milk, eggs"
    9 edits, 2 saves

A log line that cannot be read, a file that cannot be read, and a command line that
autosave-sim does not understand stop it with a message on stderr and exit status 2.

## Development

    npm test

There are no dependencies: the code is TypeScript run directly by Node 22 with
`--experimental-strip-types`, and the tests use `node:test`.
