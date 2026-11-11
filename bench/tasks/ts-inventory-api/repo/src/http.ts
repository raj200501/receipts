import type { ApiResponse } from "./types.ts";

/** Build a JSON response with the given status. */
export function json(status: number, body: unknown, headers: Record<string, string> = {}): ApiResponse {
  return { status, headers: { "content-type": "application/json", ...headers }, body };
}

/** An empty response such as 204 No Content. */
export function empty(status: number): ApiResponse {
  return { status, headers: {}, body: null };
}

/** Build the error body shared by every error response: {"error": code, ...extra}. */
export function problem(
  status: number,
  code: string,
  extra: Record<string, unknown> = {},
): ApiResponse {
  return json(status, { error: code, ...extra });
}

/** True for a plain JSON object (not null, not an array). */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
