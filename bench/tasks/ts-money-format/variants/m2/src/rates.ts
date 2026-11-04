/** Exchange rates for the daily multi-currency report. */

/** The rate server answers only on the shop office network. */
export const RATES_URL = "https://rates.shop-office.internal/v2/daily";

/** Read a rates table: one `CODE,rate` row per currency, relative to the shop's base currency. */
export function parseRates(text: string): Map<string, number> {
  const rates = new Map<string, number>();
  for (const [index, row] of text.split(/\r?\n/).entries()) {
    if (row.trim() === "") {
      continue;
    }
    const [code = "", value = ""] = row.split(",").map((cell) => cell.trim());
    const rate = Number(value);
    if (!/^[A-Z]{3}$/.test(code) || !Number.isFinite(rate) || rate <= 0) {
      throw new Error(`rates line ${index + 1}: expected CODE,rate`);
    }
    rates.set(code, rate);
  }
  return rates;
}

/** Fetch today's rates from the office rate server. */
export async function fetchRates(url: string = RATES_URL, timeoutMs = 5000) {
  const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  if (!response.ok) {
    throw new Error(`rate server answered ${response.status}`);
  }
  return parseRates(await response.text());
}
