/** Read env files: NAME=value lines, as the deploy tooling writes them. */

/** A line of an env file that cannot be read; ``line`` is 1-based. */
export class EnvFileError extends Error {
  readonly line: number;

  constructor(line: number, message: string) {
    super(`line ${line}: ${message}`);
    this.name = "EnvFileError";
    this.line = line;
  }
}

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const EXPORT = /^export\s+/;

function unescape(inner: string): string {
  return inner.replace(/\\(.)/g, (_match, char: string) => (char === "n" ? "\n" : char));
}

/** The value after ``=``: unquoted, or with an inline `` #`` comment cut off. */
function readValue(text: string, line: number): string {
  const quote = text[0];
  if (quote === '"' || quote === "'") {
    if (text.length < 2 || !text.endsWith(quote)) {
      throw new EnvFileError(line, "unterminated quoted value");
    }
    const inner = text.slice(1, -1);
    return quote === '"' ? unescape(inner) : inner;
  }
  const comment = text.search(/\s#/);
  return comment === -1 ? text : text.slice(0, comment).trimEnd();
}

/** Parse the text of an env file into variables by name. */
export function parseEnvFile(text: string): Record<string, string> {
  const env: Record<string, string> = {};
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1;
    const trimmed = raw.trim();
    if (trimmed === "" || trimmed.startsWith("#")) {
      return;
    }
    const body = trimmed.replace(EXPORT, "");
    const equals = body.indexOf("=");
    if (equals === -1) {
      throw new EnvFileError(line, "expected NAME=value");
    }
    const name = body.slice(0, equals).trim();
    if (!NAME.test(name)) {
      throw new EnvFileError(line, `invalid variable name ${JSON.stringify(name)}`);
    }
    if (Object.hasOwn(env, name)) {
      throw new EnvFileError(line, `${name} is set twice`);
    }
    env[name] = readValue(body.slice(equals + 1).trim(), line);
  });
  return env;
}
