/** The envcheck report: every setting, with secrets masked. */

import type { ConfigOf, Schema } from "./types.ts";

/** What a secret looks like in every output. */
export const MASK = "****";

/** One NAME=value line per setting, in schema order. */
export function describeConfig<S extends Schema>(schema: S, config: ConfigOf<S>): string[] {
  const values = config as Record<string, unknown>;
  return Object.entries(schema).map(([name, field]) => {
    const shown = field.secret ? MASK : field.display(values[name]);
    return `${name}=${shown}`;
  });
}

/** One setting in envcheck --json. */
export interface JsonSetting {
  kind: string;
  value: unknown;
}

/** The settings for envcheck --json, in schema order. */
export function configJson<S extends Schema>(
  schema: S,
  config: ConfigOf<S>,
): Record<string, JsonSetting> {
  const values = config as Record<string, unknown>;
  const result: Record<string, JsonSetting> = {};
  for (const [name, field] of Object.entries(schema)) {
    result[name] = { kind: field.kind, value: field.secret ? MASK : values[name] };
  }
  return result;
}
