/** Send computed due dates to the billing system's webhook. */

/** The billing system's due-date webhook; it is reachable only from the finance office network. */
export const WEBHOOK_URL = "https://billing.finance.internal/hooks/due-dates";

/** Invoices per request that the webhook accepts. */
export const MAX_RECORDS = 50;

/** One invoice as the webhook stores it; all dates are YYYY-MM-DD text. */
export interface DueRecord {
  invoice: string;
  terms: string;
  due: string;
}

/** The JSON body for a batch of records; a batch over the limit is an Error. */
export function webhookBody(records: readonly DueRecord[]): string {
  if (records.length === 0 || records.length > MAX_RECORDS) {
    throw new Error(`a batch has 1 to ${MAX_RECORDS} records, got ${records.length}`);
  }
  return JSON.stringify({ source: "dueby", records });
}

/** Post a batch to the webhook and resolve with the HTTP status of its reply. */
export async function postDueDates(
  records: readonly DueRecord[],
  url: string = WEBHOOK_URL,
  timeoutMs = 5000,
): Promise<number> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: webhookBody(records),
    signal: AbortSignal.timeout(timeoutMs),
  });
  return response.status;
}
