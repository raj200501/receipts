/** Shared types of relay-config. */

/** Environment variables by name, as in process.env (a variable may be missing). */
export type Env = Readonly<Record<string, string | undefined>>;

/** How one environment variable is read and shown. */
export interface Field<T> {
  /** The kind of value ("integer", "url", ...), shown by envcheck --json. */
  readonly kind: string;
  /** Secrets are shown as **** in every output. */
  readonly secret: boolean;
  /** One line about the setting. */
  readonly description: string;
  /** The value used when the variable is unset or empty; undefined means required. */
  readonly default?: T;
  /** Read the trimmed raw value; throws a CoercionError when it cannot. */
  parse(raw: string): T;
  /** The value as envcheck prints it. */
  display(value: T): string;
}

/** A schema: one field per environment variable, in the order they are checked. */
export type Schema = Readonly<Record<string, Field<unknown>>>;

/** The typed configuration a schema describes: each variable's name to its value. */
export type ConfigOf<S extends Schema> = {
  -readonly [K in keyof S]: S[K] extends Field<infer T> ? T : never;
};
