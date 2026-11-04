/** Publish alert rules to the shared rule registry. */

import { parse } from "./parser.ts";

/** The registry's rule endpoint; it is reachable only from the on-call network. */
export const REGISTRY_URL = "https://rules.oncall.internal/api/v1/rules";

/** A rule as the registry stores it. */
export interface RuleDocument {
  id: string;
  expression: string;
  severity: number;
}

/** The registry's document for a rule; an expression that does not parse is an Error. */
export function ruleDocument(id: string, expression: string, severity: number): RuleDocument {
  if (!/^[a-z][a-z0-9-]{2,39}$/.test(id)) {
    throw new Error(`rule ids are 3 to 40 lowercase letters, digits, or dashes, got "${id}"`);
  }
  parse(expression);
  return { id, expression, severity };
}

/** Send a rule to the registry and resolve with the HTTP status of its reply. */
export async function publishRule(
  rule: RuleDocument,
  url: string = REGISTRY_URL,
  timeoutMs = 5000,
): Promise<number> {
  const response = await fetch(url, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(rule),
    signal: AbortSignal.timeout(timeoutMs),
  });
  return response.status;
}
