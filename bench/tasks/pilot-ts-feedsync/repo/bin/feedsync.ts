/** Entry point: ``node --experimental-strip-types bin/feedsync.ts digest``. */

import { main } from "../src/cli.ts";

process.exitCode = await main(process.argv.slice(2), {
  out: (text) => process.stdout.write(text),
  err: (text) => process.stderr.write(text),
});
