/** Read and check the route manifest that the API catalog exports (format in README.md). */

import { readFileSync } from "node:fs";
import { PatternError, parsePattern } from "./pattern.ts";
import { ROUTE_METHODS } from "./types.ts";
import type { RouteDefinition, RouteMethod } from "./types.ts";

export const MANIFEST_VERSION = 3;
export const DEFAULT_MANIFEST = "routes.manifest.json";

/** A manifest that cannot be read or does not follow the format. */
export class ManifestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ManifestError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function route(raw: unknown, where: string, names: Set<string>): RouteDefinition {
  if (!isObject(raw)) {
    throw new ManifestError(`${where}: must be an object`);
  }
  const { name, method, pattern, upstream, strict } = raw;
  if (typeof name !== "string" || name === "") {
    throw new ManifestError(`${where}: name must be a non-empty string`);
  }
  if (names.has(name)) {
    throw new ManifestError(`${where}: duplicate route name ${JSON.stringify(name)}`);
  }
  names.add(name);
  const named = `${where} (${name})`;
  if (typeof method !== "string" || !(ROUTE_METHODS as readonly string[]).includes(method)) {
    throw new ManifestError(`${named}: unknown method ${JSON.stringify(method)}`);
  }
  if (typeof pattern !== "string") {
    throw new ManifestError(`${named}: pattern must be a string`);
  }
  try {
    parsePattern(pattern);
  } catch (error) {
    if (error instanceof PatternError) {
      throw new ManifestError(`${named}: ${error.message}`);
    }
    throw error;
  }
  if (typeof upstream !== "string" || !/^https?:\/\/[^\s/]+/.test(upstream)) {
    throw new ManifestError(`${named}: upstream must be an http:// or https:// URL`);
  }
  if (strict !== undefined && typeof strict !== "boolean") {
    throw new ManifestError(`${named}: strict must be true or false`);
  }
  const definition: RouteDefinition = { name, method: method as RouteMethod, pattern, upstream };
  if (strict === true) {
    definition.strict = true;
  }
  return definition;
}

/** The routes of a manifest, in order; ``source`` names the manifest in error messages. */
export function parseManifest(text: string, source: string): RouteDefinition[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ManifestError(`${source}: not valid JSON`);
  }
  if (!isObject(data)) {
    throw new ManifestError(`${source}: must be a JSON object`);
  }
  if (data.version !== MANIFEST_VERSION) {
    throw new ManifestError(
      `${source}: manifest version ${JSON.stringify(data.version)} is not supported (expected ${MANIFEST_VERSION})`,
    );
  }
  if (!Array.isArray(data.routes)) {
    throw new ManifestError(`${source}: routes must be a list`);
  }
  const names = new Set<string>();
  return data.routes.map((raw, index) => route(raw, `${source}: route ${index + 1}`, names));
}

/** Read the manifest file at ``path``. */
export function loadManifest(path: string): RouteDefinition[] {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    throw new ManifestError(`cannot read ${path}`);
  }
  return parseManifest(text, path);
}
