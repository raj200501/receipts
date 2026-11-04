/** Route patterns: their syntax (described in README.md), compiling them, and matching paths. */

import { decodeValue } from "./path.ts";
import type { Params } from "./types.ts";

/** One segment of a pattern. */
export type Segment =
  | { kind: "static"; value: string }
  | { kind: "param"; name: string }
  | { kind: "optional"; name: string }
  | { kind: "wildcard"; name: string };

/** A pattern that breaks the syntax rules. */
export class PatternError extends Error {
  constructor(pattern: string, message: string) {
    super(`invalid pattern ${JSON.stringify(pattern)}: ${message}`);
    this.name = "PatternError";
  }
}

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const SPECIAL = /[:*?]/;

function parseSegment(pattern: string, part: string): Segment {
  if (part.startsWith(":")) {
    const optional = part.endsWith("?");
    const name = part.slice(1, optional ? -1 : undefined);
    if (!NAME.test(name)) {
      throw new PatternError(pattern, `bad parameter name ${JSON.stringify(name)}`);
    }
    return optional ? { kind: "optional", name } : { kind: "param", name };
  }
  if (part.startsWith("*")) {
    const name = part.slice(1);
    if (!NAME.test(name)) {
      throw new PatternError(pattern, `bad wildcard name ${JSON.stringify(name)}`);
    }
    return { kind: "wildcard", name };
  }
  if (SPECIAL.test(part)) {
    throw new PatternError(pattern, `unexpected character in ${JSON.stringify(part)}`);
  }
  return { kind: "static", value: part };
}

/** The segments of ``pattern``; throws a PatternError when it breaks a rule. */
export function parsePattern(pattern: string): Segment[] {
  if (!pattern.startsWith("/")) {
    throw new PatternError(pattern, "it must start with /");
  }
  if (pattern === "/") {
    return [];
  }
  if (pattern.endsWith("/")) {
    throw new PatternError(pattern, "it must not end with /");
  }
  const segments: Segment[] = [];
  const names = new Set<string>();
  for (const part of pattern.slice(1).split("/")) {
    if (part === "") {
      throw new PatternError(pattern, "it has an empty segment");
    }
    const previous = segments.at(-1);
    if (previous?.kind === "wildcard") {
      throw new PatternError(pattern, "a wildcard must be the last segment");
    }
    const segment = parseSegment(pattern, part);
    if (previous?.kind === "optional" && segment.kind !== "optional") {
      throw new PatternError(pattern, "only optional parameters can follow an optional parameter");
    }
    if (segment.kind !== "static") {
      if (names.has(segment.name)) {
        throw new PatternError(pattern, `the name ${segment.name} is used twice`);
      }
      names.add(segment.name);
    }
    segments.push(segment);
  }
  return segments;
}

/** Whether the segments have no parameters, so that the pattern matches one path only. */
export function isStatic(segments: readonly Segment[]): boolean {
  return segments.every((segment) => segment.kind === "static");
}

/** A pattern compiled to a regular expression with one group per parameter. */
export interface CompiledPattern {
  pattern: string;
  strict: boolean;
  keys: string[];
  regex: RegExp;
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Compile ``pattern`` (``strict`` is the route's strict flag). */
export function compilePattern(pattern: string, strict = false): CompiledPattern {
  const keys: string[] = [];
  let source = "";
  for (const segment of parsePattern(pattern)) {
    switch (segment.kind) {
      case "static":
        source += `/${escapeRegExp(segment.value)}`;
        break;
      case "param":
        keys.push(segment.name);
        source += "/([^/]+)";
        break;
      case "optional":
        keys.push(segment.name);
        source += "/([^/]*)";
        break;
      case "wildcard":
        keys.push(segment.name);
        source += "/(.+)";
        break;
    }
  }
  return { pattern, strict, keys, regex: new RegExp(`^${source || "/"}$`) };
}

/** The parameters of ``path`` when it matches ``compiled``, or null when it does not. */
export function matchPattern(compiled: CompiledPattern, path: string): Params | null {
  const found = compiled.regex.exec(path);
  if (found === null) {
    return null;
  }
  const params: Params = {};
  compiled.keys.forEach((key, index) => {
    const value = found[index + 1];
    if (value !== undefined) {
      params[key] = decodeValue(value);
    }
  });
  return params;
}
