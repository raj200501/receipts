/**
 * Upload converted records to the data warehouse's ingest API.
 *
 * The API needs a token in the WAREHOUSE_TOKEN environment variable. The release
 * pipeline has it as a secret; developer machines do not.
 */

import type { CsvRecord } from "./records.ts";

export const INGEST_URL = "https://ingest.warehouse.internal/v1/batches";
export const TOKEN_VARIABLE = "WAREHOUSE_TOKEN";
export const BATCH_SIZE = 500;

/** One request to the ingest API: some records of one table. */
export interface Batch {
  table: string;
  sequence: number;
  records: CsvRecord[];
}

/** Split ``records`` into batches of at most ``size`` records, numbered from 1. */
export function toBatches(table: string, records: readonly CsvRecord[], size = BATCH_SIZE): Batch[] {
  if (!Number.isInteger(size) || size < 1) {
    throw new RangeError(`the batch size must be a positive integer, got ${size}`);
  }
  const batches: Batch[] = [];
  for (let start = 0; start < records.length; start += size) {
    batches.push({ table, sequence: batches.length + 1, records: records.slice(start, start + size) });
  }
  return batches;
}

/** Send one batch to the ingest API and resolve with the HTTP status of the reply. */
export async function uploadBatch(batch: Batch, timeoutMs = 5000): Promise<number> {
  const token = process.env[TOKEN_VARIABLE];
  if (token === undefined || token === "") {
    throw new Error(`${TOKEN_VARIABLE} is not set`);
  }
  const response = await fetch(INGEST_URL, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify(batch),
    signal: AbortSignal.timeout(timeoutMs),
  });
  return response.status;
}
