/** Pure admission guards. No I/O, discovery, credentials or default origin. */
export type PilotEnvironment = Readonly<Record<string, string | undefined>>;

export class PilotSafetyError extends Error {
  constructor(code: string) { super(code); this.name = "PilotSafetyError"; }
}

export function loopbackOrigin(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new PilotSafetyError("INVALID_SANDBOX_ORIGIN"); }
  if (url.protocol !== "https:" || url.origin !== value || url.username || url.password ||
      !["127.0.0.1", "127.0.0.2", "[::1]", "localhost"].includes(url.hostname)) {
    throw new PilotSafetyError("EXACT_LOOPBACK_HTTPS_ORIGIN_REQUIRED");
  }
  return url.origin;
}

export function authorizeSandbox(origin: string, env: PilotEnvironment): string {
  if (env.RUN_PARTNER_PILOTS !== "1") throw new PilotSafetyError("EXPLICIT_PILOT_OPT_IN_REQUIRED");
  if (env.NODE_TLS_REJECT_UNAUTHORIZED === "0") throw new PilotSafetyError("TLS_VERIFICATION_REQUIRED");
  const assigned = env.PARTNER_PILOTS_ORIGIN;
  if (!assigned || loopbackOrigin(assigned) !== loopbackOrigin(origin)) throw new PilotSafetyError("ROOT_ASSIGNED_ORIGIN_REQUIRED");
  return assigned;
}

export function authorizeRequest(origin: string, input: string | URL, method: string, env: PilotEnvironment): URL {
  authorizeSandbox(origin, env);
  const url = new URL(input);
  if (url.origin !== origin || url.username || url.password || url.hash) throw new PilotSafetyError("CROSS_ORIGIN_REQUEST_DENIED");
  const path = url.pathname;
  const oauthRead = ["/.well-known/openid-configuration", "/api/oauth2/.well-known/openid-configuration",
    "/api/oauth2/jwks", "/api/oauth2/userinfo"].includes(path);
  const productRead = /^\/api\/v1\/(?:objects|equipment|counterparties|contracts|documents)(?:\/[^/]+)?$/.test(path) ||
    /^\/api\/v1\/objects\/[^/]+\/monitoring$/.test(path) ||
    /^\/api\/v1\/documents\/[^/]+\/versions\/[^/]+\/content$/.test(path);
  const protocolWrite = ["/api/oauth2/token", "/api/oauth2/revoke"].includes(path) && !url.search;
  if (!((method === "GET" && (oauthRead || productRead)) || (method === "POST" && protocolWrite))) {
    throw new PilotSafetyError("ONLY_PARTNER_READS_AND_TOKEN_REVOCATION_ALLOWED");
  }
  return url;
}

export function callbackUrl(value: string, registered: string): URL {
  const expected = new URL(registered), returned = new URL(value);
  loopbackOrigin(expected.origin);
  if (returned.origin !== expected.origin || returned.pathname !== expected.pathname || returned.hash || returned.username || returned.password) {
    throw new PilotSafetyError("REGISTERED_CALLBACK_REQUIRED");
  }
  return returned;
}
