/** Shared types of the catalog client. */

/** One value in a query string. */
export type QueryPrimitive = string | number | boolean;

/** A parameter value: one value, a list of values, or null or undefined (left out). */
export type QueryValue = QueryPrimitive | readonly QueryPrimitive[] | null | undefined;

/** Parameters for a query string, written in the order of the object. */
export type QueryParams = Readonly<Record<string, QueryValue>>;

/** A parsed query string: a string per key, or an array of strings for a repeated key. */
export type ParsedQuery = Record<string, string | string[]>;
