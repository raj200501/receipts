/** Load a typed configuration from environment variables. */

import { CoercionError } from "./coerce.ts";
import type { ConfigOf, Env, Schema } from "./types.ts";

/** A variable that is not set or cannot be read. */
export class ConfigError extends Error {
  /** The environment variable the problem is about. */
  readonly variable: string;

  constructor(variable: string, reason: string) {
    super(`${variable}: ${reason}`);
    this.name = "ConfigError";
    this.variable = variable;
  }
}

/** A variable's trimmed value, or undefined when it is unset or empty. */
export function rawValue(env: Env, name: string): string | undefined {
  const value = env[name]?.trim();
  return value === undefined || value === "" ? undefined : value;
}

/**
 * Read every variable of ``schema`` from ``env`` and return the typed configuration.
 * Variables are read in schema order; the first one that is not set or cannot be read
 * stops the load with a ConfigError. Variables outside the schema are ignored.
 */
export function loadConfig<S extends Schema>(schema: S, env: Env = process.env): ConfigOf<S> {
  const config: Record<string, unknown> = {};
  for (const [name, field] of Object.entries(schema)) {
    const raw = rawValue(env, name);
    if (raw === undefined) {
      throw new ConfigError(name, "not set");
    }
    try {
      config[name] = field.parse(raw);
    } catch (error) {
      if (error instanceof CoercionError) {
        throw new ConfigError(name, error.message);
      }
      throw error;
    }
  }
  return config as ConfigOf<S>;
}
