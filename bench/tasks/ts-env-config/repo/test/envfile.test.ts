import assert from "node:assert/strict";
import { test } from "node:test";
import { EnvFileError, parseEnvFile } from "../src/envfile.ts";

test("NAME=value lines become variables", () => {
  assert.deepEqual(parseEnvFile("RELAY_PORT=9443\nRELAY_LOG_LEVEL=info\n"), {
    RELAY_PORT: "9443",
    RELAY_LOG_LEVEL: "info",
  });
});

test("blank lines and comment lines are skipped", () => {
  const text = "# relay settings\n\nRELAY_PORT=9443\n   # indented comment\n";
  assert.deepEqual(parseEnvFile(text), { RELAY_PORT: "9443" });
});

test("an export prefix is allowed", () => {
  assert.deepEqual(parseEnvFile("export RELAY_PORT=9443\n"), { RELAY_PORT: "9443" });
});

test("quoted values keep their spaces and # signs", () => {
  const text = "A=' spaced value '\nB=\"room #4\"\n";
  assert.deepEqual(parseEnvFile(text), { A: " spaced value ", B: "room #4" });
});

test("double quotes understand backslash escapes", () => {
  assert.deepEqual(parseEnvFile('A="two\\nlines"\nB="say \\"hi\\""\n'), {
    A: "two\nlines",
    B: 'say "hi"',
  });
});

test("an inline comment ends an unquoted value", () => {
  assert.deepEqual(parseEnvFile("RELAY_RETRY_LIMIT=3 # per webhook\nTAG=a#b\n"), {
    RELAY_RETRY_LIMIT: "3",
    TAG: "a#b",
  });
});

test("a line without = names its line number", () => {
  assert.throws(() => parseEnvFile("A=1\n\nRELAY_PORT\n"), {
    name: "EnvFileError",
    message: "line 3: expected NAME=value",
  });
});

test("bad names, open quotes, and repeated names are rejected", () => {
  assert.throws(() => parseEnvFile("9LIVES=1\n"), /line 1: invalid variable name "9LIVES"/);
  assert.throws(() => parseEnvFile("A=\"open\n"), /line 1: unterminated quoted value/);
  assert.throws(() => parseEnvFile("A=1\nA=2\n"), (error: unknown) => {
    return error instanceof EnvFileError && error.line === 2 && /A is set twice/.test(error.message);
  });
});
