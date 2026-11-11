/** Which catalog API version a server runs, and whether this client supports it. */

/** The catalog API versions this client can talk to. */
export const SUPPORTED_VERSIONS: readonly number[] = [2];

/** The staging catalog API; it is reachable only from the deploy network. */
export const STAGING_URL = "https://catalog.staging.internal";

/** The URL of a server's version endpoint. */
export function versionUrl(base: string): string {
  return `${base.replace(/\/+$/, "")}/version`;
}

/** Whether this client can talk to a server that runs API ``version``. */
export function isSupported(version: number): boolean {
  return SUPPORTED_VERSIONS.includes(version);
}

/** The API version that a server reports at its version endpoint. */
export async function serverVersion(base: string, timeoutMs = 5000): Promise<number> {
  const url = versionUrl(base);
  const response = await fetch(url, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) {
    throw new Error(`${url}: HTTP ${response.status}`);
  }
  const body = (await response.json()) as { apiVersion?: unknown };
  if (typeof body.apiVersion !== "number") {
    throw new Error(`${url}: the response has no apiVersion`);
  }
  return body.apiVersion;
}
