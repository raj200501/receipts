/** Access to the internal package registry used by the release job. */

export const REGISTRY_URL = "https://registry.platform.internal/npm/";

/** The registry token from the CI environment; throws when the secret is not provided. */
export function registryToken(env: Record<string, string | undefined> = process.env): string {
  const token = env.REGISTRY_TOKEN;
  if (token === undefined || token === "") {
    throw new Error("REGISTRY_TOKEN is not set");
  }
  return token;
}

/** The Authorization header value for registry requests. */
export function registryAuthHeader(env: Record<string, string | undefined> = process.env): string {
  return `Bearer ${registryToken(env)}`;
}
