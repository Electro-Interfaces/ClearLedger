import * as oidc from "openid-client";
import type { sandboxTransport } from "./transport.ts";
import { callbackUrl } from "./guards.ts";
import { contract } from "./scenarios.ts";

export type OAuthClient = { clientId: string; clientSecret?: string; scopes: string[]; grantId?: string; redirectUri?: string };
type Transport = ReturnType<typeof sandboxTransport>;

export async function discover(origin: string, input: OAuthClient, transport: Transport, delegated = false) {
  const config = await oidc.discovery(new URL(origin), input.clientId, undefined,
    input.clientSecret ? oidc.ClientSecretBasic(input.clientSecret) : oidc.None(), {
      [oidc.customFetch]: transport.customFetch, timeout: 15,
      execute: delegated ? [oidc.enableNonRepudiationChecks] : [],
    });
  contract(config.serverMetadata().issuer === origin, "EXACT_ISSUER_REQUIRED");
  return config;
}

export async function machine(config: oidc.Configuration, input: OAuthClient) {
  contract(input.clientSecret && input.grantId && input.scopes.length, "APPROVED_MACHINE_GRANT_REQUIRED");
  contract(!input.scopes.some(scope => ["openid", "profile", "email", "offline_access", "documents:read", "documents.files:download"].includes(scope)),
    "MACHINE_IDENTITY_AND_DOCUMENT_SCOPES_FORBIDDEN");
  const tokens = await oidc.clientCredentialsGrant(config, { grant_id: input.grantId, scope: input.scopes.join(" ") });
  contract(tokens.access_token && tokens.token_type.toLowerCase() === "bearer", "ACCESS_TOKEN_REQUIRED");
  contract(tokens.id_token === undefined && tokens.refresh_token === undefined, "MACHINE_CANNOT_RECEIVE_ID_OR_REFRESH");
  return { tokens, receivedAt: Date.now() };
}

export async function delegatedRequest(config: oidc.Configuration, input: OAuthClient) {
  contract(input.redirectUri && input.scopes.includes("openid") && input.scopes.includes("documents:read"), "DELEGATED_DOCUMENT_SCOPES_REQUIRED");
  contract(!input.scopes.includes("docs:read") && !input.scopes.includes("offline_access"), "PORTAL_AND_REFRESH_OUTSIDE_THIS_PILOT");
  const verifier = oidc.randomPKCECodeVerifier(), state = oidc.randomState(), nonce = oidc.randomNonce();
  const url = oidc.buildAuthorizationUrl(config, { response_type: "code", redirect_uri: input.redirectUri,
    scope: input.scopes.join(" "), state, nonce, code_challenge: await oidc.calculatePKCECodeChallenge(verifier),
    code_challenge_method: "S256", prompt: "consent" });
  contract(url.origin === config.serverMetadata().issuer && url.pathname === "/api/oauth2/authorize", "CANONICAL_AUTHORIZATION_ENDPOINT_REQUIRED");
  return { url, state, nonce, verifier, createdAt: Date.now() };
}

export async function delegatedExchange(config: oidc.Configuration, input: OAuthClient,
  request: Awaited<ReturnType<typeof delegatedRequest>>, returned: string, onPhase: (phase: string) => void = () => {}) {
  contract(Date.now() - request.createdAt < 5 * 60 * 1000 && input.redirectUri, "AUTHORIZATION_TRANSACTION_EXPIRED");
  const url = callbackUrl(returned, input.redirectUri);
  const checks = { pkceCodeVerifier: request.verifier, expectedState: request.state, expectedNonce: request.nonce, idTokenExpected: true };
  onPhase("authorization-code-grant-and-strict-id-token-validation");
  const tokens = await oidc.authorizationCodeGrant(config, url, checks, { redirect_uri: input.redirectUri });
  onPhase("token-response-contract");
  contract(tokens.id_token && tokens.access_token && tokens.token_type.toLowerCase() === "bearer", "DELEGATED_ACCESS_AND_ID_TOKEN_REQUIRED");
  contract(tokens.refresh_token === undefined, "NO_UNREQUESTED_REFRESH");
  const claims = tokens.claims();
  contract(claims && typeof claims.sub === "string", "VALIDATED_IDENTITY_REQUIRED");
  onPhase("userinfo-subject-validation");
  const info = await oidc.fetchUserInfo(config, tokens.access_token, claims.sub);
  contract(info.sub === claims.sub && !["access_token", "refresh_token", "id_token"].some(key => key in info), "USERINFO_IS_IDENTITY_NOT_API_CREDENTIALS");
  onPhase("complete");
  return { tokens, receivedAt: Date.now(), subject: claims.sub };
}

export function freshForControl(issued: { tokens: oidc.TokenEndpointResponse; receivedAt: number }, seconds = 15) {
  contract(typeof issued.tokens.expires_in === "number" &&
    issued.receivedAt + issued.tokens.expires_in * 1000 > Date.now() + seconds * 1000, "CONTROL_TOKEN_TOO_OLD");
}

export { oidc };
