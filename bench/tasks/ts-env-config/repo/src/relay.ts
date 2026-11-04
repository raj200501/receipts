/** The relay's settings: its schema and how it is loaded. */

import { boolean, duration, integer, list, oneOf, string, url } from "./fields.ts";
import { loadConfig } from "./load.ts";
import type { ConfigOf, Env } from "./types.ts";

export const LOG_LEVELS = ["debug", "info", "warn", "error"] as const;

/** Every setting of the relay, in the order envcheck checks and prints them. */
export const RELAY_SCHEMA = {
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

/** The relay's typed configuration. */
export type RelayConfig = ConfigOf<typeof RELAY_SCHEMA>;

/** Load the relay's configuration from ``env`` (throws a ConfigError). */
export function loadRelayConfig(env: Env = process.env): RelayConfig {
  return loadConfig(RELAY_SCHEMA, env);
}
