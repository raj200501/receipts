/** Published versions of a package, from the internal artifact registry. */

/** The registry API; it is reachable only from the build network. */
export const REGISTRY_URL = "https://registry.build.internal/api/v2";

/** The registry URL that lists the published versions of ``name``. */
export function versionsUrl(name: string, registry: string = REGISTRY_URL): string {
  return `${registry}/packages/${encodeURIComponent(name)}/versions`;
}

/** The registry token. The CI runners provide it as REGISTRY_TOKEN. */
export function registryToken(
  env: Readonly<Record<string, string | undefined>> = process.env,
): string {
  const token = env.REGISTRY_TOKEN;
  if (token === undefined || token === "") {
    throw new Error("REGISTRY_TOKEN is not set; the CI runners provide it");
  }
  return token;
}

/** The published versions of ``name``, in the order the registry lists them. */
export async function publishedVersions(
  name: string,
  env: Readonly<Record<string, string | undefined>> = process.env,
  timeoutMs = 5000,
): Promise<string[]> {
  const url = versionsUrl(name);
  const response = await fetch(url, {
    headers: { authorization: `Bearer ${registryToken(env)}`, accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) {
    throw new Error(`${url}: HTTP ${response.status}`);
  }
  const body = (await response.json()) as { versions?: unknown };
  if (!Array.isArray(body.versions)) {
    throw new Error(`${url}: the response lists no versions`);
  }
  return body.versions.map(String);
}
