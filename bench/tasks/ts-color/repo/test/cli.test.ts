import assert from "node:assert/strict";
import { test } from "node:test";
import { main } from "../src/cli.ts";

function run(argv: string[]): { status: number; out: string; err: string } {
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

test("convert prints hex by default", () => {
  assert.deepEqual(run(["convert", "rgb(51, 102, 153)"]), {
    status: 0,
    out: "#336699\n",
    err: "",
  });
});

test("convert --to rgb prints rgb()", () => {
  assert.equal(run(["convert", "#369", "--to", "rgb"]).out, "rgb(51, 102, 153)\n");
});

test("convert rejects an unknown notation", () => {
  const result = run(["convert", "#369", "--to", "cmyk"]);
  assert.equal(result.status, 2);
  assert.match(result.err, /^color: unknown notation "cmyk"/);
});

test("convert reports a color it cannot read with status 2", () => {
  const result = run(["convert", "blue"]);
  assert.equal(result.status, 2);
  assert.match(result.err, /^color: "blue" is not a color/);
  assert.equal(result.out, "");
});

test("mix blends at the midpoint by default", () => {
  assert.equal(run(["mix", "#000", "#fff"]).out, "#808080\n");
});

test("mix --amount sets the blend", () => {
  assert.equal(run(["mix", "#ff0000", "#0000ff", "--amount", "0.25"]).out, "#bf0040\n");
});

test("mix needs two colors and a numeric amount", () => {
  assert.equal(run(["mix", "#fff"]).status, 2);
  assert.equal(run(["mix", "#fff", "#000", "--amount", "lots"]).status, 2);
});

test("help prints the usage and a missing command is an error", () => {
  const help = run(["help"]);
  assert.equal(help.status, 0);
  assert.match(help.out, /^usage: color/);
  assert.equal(run([]).status, 2);
  assert.equal(run(["paint"]).status, 2);
});
