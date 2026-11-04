/** Entry point: ``node --experimental-strip-types bin/csvtool.ts json FILE``. */

import { main } from "../src/cli.ts";

process.exitCode = main(process.argv.slice(2), {
  out: (text) => process.stdout.write(text),
  err: (text) => process.stderr.write(text),
});
