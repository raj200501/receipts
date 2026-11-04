/** Field builders: one for each kind of setting. */

import {
  CoercionError,
  formatDuration,
  parseBoolean,
  parseDuration,
  parseInteger,
  parseList,
  parseUrl,
} from "./coerce.ts";
import type { Field } from "./types.ts";

/** Options every field builder takes. */
export interface FieldOptions {
  /** Show the value as **** in every output. */
  secret?: boolean;
  /** One line about the setting. */
  description?: string;
}

function makeField<T>(
  kind: string,
  parse: (raw: string) => T,
  display: (value: T) => string,
  options: FieldOptions,
): Field<T> {
  return {
    kind,
    secret: options.secret ?? false,
    description: options.description ?? "",
    parse,
    display,
  };
}

/** Options of string(). */
export interface StringOptions extends FieldOptions {
  /** The shortest value accepted (1 by default). */
  minLength?: number;
}

/** Any text of at least ``minLength`` characters. The error never shows the value. */
export function string(options: StringOptions = {}): Field<string> {
  const minLength = options.minLength ?? 1;
  return makeField(
    "string",
    (raw) => {
      if (raw.length < minLength) {
        throw new CoercionError(`expected at least ${minLength} characters, got ${raw.length}`);
      }
      return raw;
    },
    (value) => value,
    options,
  );
}

/** Options of integer(). */
export interface IntegerOptions extends FieldOptions {
  /** The smallest value accepted. */
  min?: number;
  /** The largest value accepted. */
  max?: number;
}

/** A whole number, optionally limited to ``min`` to ``max``. */
export function integer(options: IntegerOptions = {}): Field<number> {
  const min = options.min ?? Number.MIN_SAFE_INTEGER;
  const max = options.max ?? Number.MAX_SAFE_INTEGER;
  return makeField(
    "integer",
    (raw) => {
      const value = parseInteger(raw);
      if (value < min || value > max) {
        throw new CoercionError(`expected an integer from ${min} to ${max}, got ${value}`);
      }
      return value;
    },
    (value) => String(value),
    options,
  );
}

/** true or false (see parseBoolean for the words accepted). */
export function boolean(options: FieldOptions = {}): Field<boolean> {
  return makeField("boolean", parseBoolean, (value) => String(value), options);
}

/** A duration such as 30s, as milliseconds. */
export function duration(options: FieldOptions = {}): Field<number> {
  return makeField("duration", parseDuration, formatDuration, options);
}

/** Comma-separated items. */
export function list(options: FieldOptions = {}): Field<string[]> {
  return makeField("list", parseList, (value) => value.join(","), options);
}

/** Options of url(). */
export interface UrlOptions extends FieldOptions {
  /** The schemes accepted, without the colon (any scheme by default). */
  protocols?: readonly string[];
}

/** An absolute URL, as its normalized href. */
export function url(options: UrlOptions = {}): Field<string> {
  const protocols = options.protocols ?? [];
  return makeField("url", (raw) => parseUrl(raw, protocols), (value) => value, options);
}

/** One word of a fixed list. */
export function oneOf<const T extends string>(
  choices: readonly T[],
  options: FieldOptions = {},
): Field<T> {
  return makeField(
    "choice",
    (raw) => {
      const choice = choices.find((item) => item === raw);
      if (choice === undefined) {
        throw new CoercionError(`expected one of ${choices.join(", ")}, got ${JSON.stringify(raw)}`);
      }
      return choice;
    },
    (value) => value,
    options,
  );
}
