import assert from "node:assert/strict";
import { test } from "node:test";
import { KeystrokeError, parseKeystrokes } from "../src/keystrokes.ts";

test("edits and closes are read with their times and lines", () => {
  assert.deepEqual(parseKeystrokes("0 type H\n120 type Hi\n900 close\n"), [
    { kind: "type", time: 0, text: "H", line: 1 },
    { kind: "type", time: 120, text: "Hi", line: 2 },
    { kind: "close", time: 900, line: 3 },
  ]);
});

test("the text keeps its spaces and may be empty", () => {
  const events = parseKeystrokes("0 type a  b \r\n10 type\n20 type \n");
  assert.deepEqual(
    events.map((event) => (event.kind === "type" ? event.text : "")),
    ["a  b ", "", ""],
  );
});

test("comments and blank lines are skipped", () => {
  const events = parseKeystrokes("# typing test\n\n  # indented comment\n5 type x\n");
  assert.deepEqual(events, [{ kind: "type", time: 5, text: "x", line: 4 }]);
});

test("a line that is not an event is a KeystrokeError naming its line", () => {
  assert.throws(() => parseKeystrokes("0 type a\n10 paste b\n"), {
    name: "KeystrokeError",
    message: 'line 2: expected "TIME type TEXT" or "TIME close", got "10 paste b"',
  });
  assert.throws(() => parseKeystrokes("-5 type a\n"), KeystrokeError);
});

test("times must not go down", () => {
  assert.throws(() => parseKeystrokes("100 type a\n100 type ab\n50 type abc\n"), {
    message: "line 3: time 50 is earlier than the time before it (100)",
  });
});
