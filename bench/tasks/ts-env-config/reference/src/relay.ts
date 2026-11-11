/** The relay's settings: its schema, the platform defaults, and how it is loaded. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { CoercionError } from "./coerce.ts";
import { boolean, duration, integer, list, oneOf, string, url, withDefault } from "./fields.ts";
import { loadConfig, rawValue } from "./load.ts";
import type { ConfigOf, Env, Field, Schema } from "./types.ts";

export const LOG_LEVELS = ["debug", "info", "warn", "error"] as const;

/** The platform team's defaults for the relay (config/defaults.json). */
export const DEFAULTS_FILE = fileURLToPath(new URL("../config/defaults.json", import.meta.url));

/**
 * The platform defaults: variable names to values written as in the environment. A file
 * without a "defaults" object has no defaults.
 */
export function readPlatformDefaults(file: string = DEFAULTS_FILE): Record<string, string> {
  const data: unknown = JSON.parse(readFileSync(file, "utf8"));
  const defaults = (data as { defaults?: unknown } | null)?.defaults;
  if (defaults === undefined) {
    return {};
  }
  if (typeof defaults !== "object" || defaults === null || Array.isArray(defaults)) {
    throw new Error(`${file}: "defaults" must be an object`);
  }
  const result: Record<string, string> = {};
  for (const [name, value] of Object.entries(defaults)) {
    if (typeof value !== "string") {
      throw new Error(`${file}: the default of ${name} must be a string`);
    }
    result[name] = value;
  }
  return result;
}

/**
 * ``schema`` with the raw ``defaults`` read by each field. Secrets never take a default,
 * and a default that cannot be read is an error that names the file.
 */
export function applyDefaults<S extends Schema>(
  schema: S,
  defaults: Readonly<Record<string, string>>,
  file: string = DEFAULTS_FILE,
): S {
  const result: Record<string, Field<unknown>> = {};
  for (const [name, field] of Object.entries(schema)) {
    const raw = rawValue(defaults, name);
    if (raw === undefined) {
      result[name] = field;
      continue;
    }
    if (field.secret) {
      throw new Error(`${file}: ${name} is a secret and cannot have a default`);
    }
    try {
      result[name] = withDefault(field, field.parse(raw));
    } catch (error) {
      if (error instanceof CoercionError) {
        throw new Error(`${file}: ${name}: ${error.message}`);
      }
      throw error;
    }
  }
  return result as unknown as S;
}

const FIELDS = {
  RELAY_PORT: integer({ min: 1, max: 65535, description: "port the relay listens on" }),
  RELAY_UPSTREAM_URL: url({
    protocols: ["https"],
    description: "where verified webhooks are forwarded",
  }),
  RELAY_SIGNING_SECRET: string({
    secret: true,
    minLength: 32,
    description: "key that verifies webhook signatures",
  }),
  RELAY_LOG_LEVEL: oneOf(LOG_LEVELS, { description: "log verbosity" }),
  RELAY_TIMEOUT: duration({ description: "time limit for one upstream request" }),
  RELAY_RETRY_LIMIT: integer({
    min: 0,
    max: 10,
    description: "retries before a webhook goes to the dead-letter queue",
  }),
  RELAY_ALLOWED_EVENTS: list({ description: "event types the relay forwards" }),
  RELAY_QUEUE_URL: url({ description: "the dead-letter queue" }),
  RELAY_VERIFY_TLS: boolean({ description: "verify the upstream's TLS certificate" }),
};

/**
 * Every setting of the relay, in the order envcheck checks and prints them, with the
 * platform defaults of config/defaults.json.
 */
export const RELAY_SCHEMA = applyDefaults(FIELDS, readPlatformDefaults());

/** The relay's typed configuration. */
export type RelayConfig = ConfigOf<typeof RELAY_SCHEMA>;

/** Load the relay's configuration from ``env`` (throws a ConfigError). */
export function loadRelayConfig(env: Env = process.env): RelayConfig {
  return loadConfig(RELAY_SCHEMA, env);
}
