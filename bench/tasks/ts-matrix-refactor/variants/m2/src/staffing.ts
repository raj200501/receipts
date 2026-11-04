/** Publish a forecast to the support team's staffing planner. */

import { formatDay } from "./dates.ts";
import type { DayForecast } from "./forecast.ts";

/** The planner's forecast endpoint; it is reachable only from the support office network. */
export const PLANNER_URL = "https://planner.support.internal/api/v2/forecasts";

/** Tickets one agent handles in a shift, as the planner counts them. */
export const TICKETS_PER_AGENT = 40;

/** One day as the planner stores it. */
export interface PlannerDay {
  date: string;
  tickets: number;
  agents: number;
}

/** The document the planner accepts for one queue. */
export interface PlannerDocument {
  queue: string;
  days: PlannerDay[];
}

/** The planner document for a forecast: whole tickets and the agents they need. */
export function plannerDocument(queue: string, rows: readonly DayForecast[]): PlannerDocument {
  return {
    queue,
    days: rows.map((row) => {
      const tickets = Math.round(row.tickets);
      return { date: formatDay(row.day), tickets, agents: Math.ceil(tickets / TICKETS_PER_AGENT) };
    }),
  };
}

/** Send a document to the planner and resolve with the HTTP status of its reply. */
export async function publishForecast(
  document: PlannerDocument,
  url: string = PLANNER_URL,
  timeoutMs = 5000,
): Promise<number> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(document),
    signal: AbortSignal.timeout(timeoutMs),
  });
  return response.status;
}
