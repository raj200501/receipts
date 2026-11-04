/** Read feed documents from files or from https:// URLs. */

import { readFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

export const FETCH_TIMEOUT_MS = 10_000;

/** A feed source that cannot be read. */
export class SourceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SourceError";
  }
}

async function fetchText(url: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(url, { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new SourceError(`could not fetch ${url}: ${reason}`);
  }
  if (!response.ok) {
    throw new SourceError(`could not fetch ${url}: HTTP ${response.status}`);
  }
  return response.text();
}

/** The text of a feed source: an https:// URL, or a file path relative to ``root``. */
export async function readSource(source: string, root: string): Promise<string> {
  if (/^https?:\/\//.test(source)) {
    return fetchText(source);
  }
  if (source.includes("://")) {
    throw new SourceError(`unsupported feed source ${source}`);
  }
  try {
    return await readFile(isAbsolute(source) ? source : join(root, source), "utf8");
  } catch {
    throw new SourceError(`feed file not found: ${source}`);
  }
}
