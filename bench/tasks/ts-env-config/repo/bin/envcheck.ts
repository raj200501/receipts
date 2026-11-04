/** Entry point: ``node --experimental-strip-types bin/envcheck.ts [--env-file FILE] [--json]``. */

import { main } from "../src/cli.ts";

process.exitCode = main(process.argv.slice(2), process.env, {
  out: (text) => process.stdout.write(text),
  err: (text) => process.stderr.write(text),
});
