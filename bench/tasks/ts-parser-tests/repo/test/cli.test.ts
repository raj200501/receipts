import assert from "node:assert/strict";
import { test } from "node:test";
import { main } from "../src/cli.ts";

function run(...argv: string[]): { status: number; out: string; err: string } {
  let out = "";
  let err = "";
  const status = main(argv, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { status, out, err };
}

test("tokens lists the tokens with their places", () => {
  const result = run("tokens", "x <= 10");
  assert.equal(result.status, 0);
  assert.equal(result.out, "1:1 name    x\n1:3 operator<=\n1:6 number  10\n");
});

test("eval prints the value of the expression", () => {
  assert.equal(run("eval", "(a + 1) * 2", "--var", "a=4").out, "10\n");
  assert.equal(run("eval", "name + '!'", "--var", "name=hi").out, '"hi!"\n');
});

test("a lexical error stops with status 2", () => {
  const result = run("tokens", "a @ b");
  assert.equal(result.status, 2);
  assert.equal(result.out, "");
  assert.equal(result.err, 'exprlex: unexpected character "@" at line 1, column 3\n');
});

test("a syntax error and an evaluation error stop with status 2", () => {
  assert.equal(run("eval", "1 +").status, 2);
  assert.equal(run("eval", "nope").err, 'exprlex: unknown name "nope"\n');
});

test("a malformed command prints the usage with status 2", () => {
  assert.equal(run().status, 2);
  assert.match(run("tokens").err, /^usage: exprlex/);
  assert.equal(run("eval", "1", "--var", "novalue").status, 2);
});
