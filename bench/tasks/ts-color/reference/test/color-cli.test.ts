import assert from "node:assert/strict";
import { test } from "node:test";
import { main } from "../src/cli.ts";
import { parseColor } from "../src/parse.ts";

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

test("parseColor reads hsl()", () => {
  assert.deepEqual(parseColor("hsl(120, 50%, 50%)"), { r: 64, g: 191, b: 64 });
  assert.deepEqual(parseColor(" hsl( 0 ,100% , 50% ) "), { r: 255, g: 0, b: 0 });
  assert.deepEqual(parseColor("hsl(-120, 100%, 50%)"), { r: 0, g: 0, b: 255 });
});

test("parseColor rejects hsl() without percent signs or with values out of range", () => {
  for (const bad of ["hsl(120, 50, 50)", "hsl(120, 150%, 50%)", "hsl(120, 50%)"]) {
    assert.throws(() => parseColor(bad), /color|hsl/, bad);
  }
});

test("convert --to hsl prints whole numbers", () => {
  assert.equal(run(["convert", "#336699", "--to", "hsl"]).out, "hsl(210, 50%, 40%)\n");
});

test("convert reads hsl() input", () => {
  assert.equal(run(["convert", "hsl(120, 50%, 50%)"]).out, "#40bf40\n");
});

test("contrast prints the ratio and the four verdicts", () => {
  assert.equal(
    run(["contrast", "#767676", "#ffffff"]).out,
    "ratio 4.54:1\nAA normal pass\nAA large pass\nAAA normal fail\nAAA large pass\n",
  );
});

test("contrast needs two readable colors", () => {
  assert.equal(run(["contrast", "#fff"]).status, 2);
  assert.equal(run(["contrast", "#fff", "nope"]).status, 2);
});
