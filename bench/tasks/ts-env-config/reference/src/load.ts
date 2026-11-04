/** Load a typed configuration from environment variables. */

import { CoercionError } from "./coerce.ts";
import type { ConfigOf, Env, Schema } from "./types.ts";

/** One variable that is not set or cannot be read. */
export interface ConfigIssue {
  /** The environment variable. */
  readonly variable: string;
  /** What is wrong, without the variable name ("not set", 'expected an integer, got "80a"'). */
  readonly message: string;
}

/** Every variable of a load that is not set or cannot be read. */
export class ConfigError extends Error {
  /** One entry per problem, in schema order. */
  readonly issues: readonly ConfigIssue[];
  /** The first variable with a problem. */
  readonly variable: string;

  constructor(issues: readonly ConfigIssue[]) {
    super(issues.map((issue) => `${issue.variable}: ${issue.message}`).join("; "));
    this.name = "ConfigError";
    this.issues = issues;
    this.variable = issues[0]?.variable ?? "";
  }
}

/** A variable's trimmed value, or undefined when it is unset or empty. */
export function rawValue(env: Env, name: string): string | undefined {
  const value = env[name]?.trim();
  return value === undefined || value === "" ? undefined : value;
}

/** A copy of a default, so that changing a loaded list never changes the default. */
function copyOf(value: unknown): unknown {
  return Array.isArray(value) ? [...value] : value;
}

/**
 * Read every variable of ``schema`` from ``env`` and return the typed configuration.
 * A variable that is unset or empty takes its field's default; without a default it is
 * required. Every variable is checked before the load fails: the ConfigError lists all
 * problems in schema order. Variables outside the schema are ignored.
 */
export function loadConfig<S extends Schema>(schema: S, env: Env = process.env): ConfigOf<S> {
  const config: Record<string, unknown> = {};
  const issues: ConfigIssue[] = [];
  for (const [name, field] of Object.entries(schema)) {
    const raw = rawValue(env, name);
    if (raw === undefined) {
      if (field.default === undefined) {
        issues.push({ variable: name, message: "not set" });
      } else {
        config[name] = copyOf(field.default);
      }
      continue;
    }
    try {
      config[name] = field.parse(raw);
    } catch (error) {
      if (!(error instanceof CoercionError)) {
        throw error;
      }
      issues.push({ variable: name, message: error.message });
    }
  }
  if (issues.length > 0) {
    throw new ConfigError(issues);
  }
  return config as ConfigOf<S>;
}
