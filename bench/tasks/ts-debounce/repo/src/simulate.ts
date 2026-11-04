/** Replaying a keystroke log through the autosave of one field, on a manual clock. */

import type { AutosaveDelays, Draft, NoteField } from "./autosave.ts";
import { createAutosave } from "./autosave.ts";
import type { KeystrokeEvent } from "./keystrokes.ts";
import { ManualScheduler } from "./scheduler.ts";

/** A saved draft and the time it was saved. */
export interface SavedDraft {
  time: number;
  draft: Draft;
}

/** What happened when a log was replayed. */
export interface Simulation {
  field: NoteField;
  delays: Readonly<AutosaveDelays>;
  edits: number;
  saves: SavedDraft[];
}

/** Options of simulate. */
export interface SimulateOptions {
  /** The field whose autosave is replayed (default body). */
  field?: NoteField;
  /** Delays to try instead of the field's. */
  delays?: AutosaveDelays;
}

/**
 * Replay ``events``: time moves to each event in turn, edits go to the autosave, and a
 * close flushes it. After the last event, time runs on until every waiting draft is
 * saved.
 */
export function simulate(events: readonly KeystrokeEvent[], options: SimulateOptions = {}): Simulation {
  const scheduler = new ManualScheduler();
  const field = options.field ?? "body";
  const saves: SavedDraft[] = [];
  const autosave = createAutosave({
    noteId: "simulated",
    field,
    save: (draft) => saves.push({ time: scheduler.now(), draft }),
    delays: options.delays,
    scheduler,
  });
  let edits = 0;
  for (const event of events) {
    scheduler.advanceTo(event.time);
    if (event.kind === "type") {
      autosave.edit(event.text);
      edits += 1;
    } else {
      autosave.flush();
    }
  }
  scheduler.runAll();
  return { field, delays: autosave.delays, edits, saves };
}

function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** The simulator's report: the delays, one line per saved draft, and a summary. */
export function formatSimulation(result: Simulation): string {
  const { wait, maxWait } = result.delays;
  const delays = maxWait === undefined ? `wait ${wait} ms` : `wait ${wait} ms, max wait ${maxWait} ms`;
  const lines = [`autosave of ${result.field} (${delays})`];
  for (const { time, draft } of result.saves) {
    lines.push(`${String(time).padStart(6)} ms  saved r${draft.revision} ${JSON.stringify(draft.text)}`);
  }
  lines.push(`${count(result.edits, "edit")}, ${count(result.saves.length, "save")}`);
  return `${lines.join("\n")}\n`;
}
