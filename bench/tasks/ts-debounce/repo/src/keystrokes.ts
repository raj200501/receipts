/** Keystroke logs, the input of the simulator: one event per line. */

/** One event of a keystroke log; ``line`` is its 1-based line number. */
export type KeystrokeEvent =
  | { kind: "type"; time: number; text: string; line: number }
  | { kind: "close"; time: number; line: number };

/** A log line that cannot be read. */
export class KeystrokeError extends Error {
  line: number;

  constructor(line: number, message: string) {
    super(`line ${line}: ${message}`);
    this.name = "KeystrokeError";
    this.line = line;
  }
}

const TYPE = /^(\d+) type(?: (.*))?$/;
const CLOSE = /^(\d+) close$/;

/**
 * Read a keystroke log. ``TIME type TEXT`` is an edit (TEXT, which may be empty, is the
 * whole text of the field after the edit) and ``TIME close`` closes the note; TIME is
 * whole milliseconds from the start and must not go down. Blank lines and lines
 * starting with "#" are skipped. Throws a KeystrokeError naming the first bad line.
 */
export function parseKeystrokes(text: string): KeystrokeEvent[] {
  const events: KeystrokeEvent[] = [];
  let last = 0;
  text.split("\n").forEach((raw, index) => {
    const line = index + 1;
    const content = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    if (content.trim() === "" || content.trimStart().startsWith("#")) {
      return;
    }
    const typed = TYPE.exec(content);
    const closed = typed === null ? CLOSE.exec(content) : null;
    const match = typed ?? closed;
    if (match === null) {
      throw new KeystrokeError(
        line,
        `expected "TIME type TEXT" or "TIME close", got ${JSON.stringify(content)}`,
      );
    }
    const time = Number(match[1]);
    if (!Number.isSafeInteger(time)) {
      throw new KeystrokeError(line, `time ${match[1]} is too large`);
    }
    if (time < last) {
      throw new KeystrokeError(line, `time ${time} is earlier than the time before it (${last})`);
    }
    last = time;
    if (typed !== null) {
      events.push({ kind: "type", time, text: typed[2] ?? "", line });
    } else {
      events.push({ kind: "close", time, line });
    }
  });
  return events;
}
