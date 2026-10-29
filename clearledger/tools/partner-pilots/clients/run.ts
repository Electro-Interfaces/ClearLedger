import { readFile, writeFile, mkdir, stat, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline/promises";
import { authorizeSandbox } from "./guards.ts";
import { sandboxTransport } from "./transport.ts";
import type { Observation } from "./transport.ts";
import { ReadApplication, contract, rentalScenario, operationsScenario } from "./scenarios.ts";
import type { Vectors, Result } from "./scenarios.ts";
import { discover, machine, delegatedRequest, delegatedExchange, freshForControl, oidc } from "./oauth.ts";
import type { OAuthClient } from "./oauth.ts";

type MachinePilot = OAuthClient & { vectors: Vectors };
type Manifest = {
  origin: string; caFile: string; runId: string; sourceRevision: string;
  rental: MachinePilot;
  operations: MachinePilot & { afterNarrowObjects: string[] };
  documents: OAuthClient & { vectors: Vectors; allowedContent: { docId: string; versionId: string; sha256: string };
    deniedContent: { docId: string; versionId: string }[] };
};

/** Adapt only the root-supplied public fixture manifest, never server models. */
function assignedManifest(value: unknown): Manifest {
  const manifest = value as Manifest;
  for (const pilot of [manifest.rental, manifest.operations, manifest.documents]) {
    const policy = (pilot as OAuthClient & { resourceScopes?: Record<string, { mode?: string }> }).resourceScopes;
    for (const [kind, vector] of Object.entries(pilot.vectors)) {
      const mode = vector.mode || policy?.[kind]?.mode;
      contract(mode === "ALL" || mode === "SET", "EFFECTIVE_FIXTURE_RESOURCE_MODE_REQUIRED");
      vector.mode = mode;
    }
  }
  // ALL still intersects kind/location/user/domain ceilings. Never derive an
  // effective vector from a company's raw fixture resource inventory.
  return manifest;
}

const work = fileURLToPath(new URL("../../../.artifacts/partner-pilot-client/", import.meta.url));
const observations: Observation[] = [], results: Result[] = [];
const docsOnly = process.argv.slice(2).length === 1 && process.argv[2] === "--docs-only";
const resultFile = docsOnly ? "results-documents.json" : "results.json";
const input = createInterface({ input: process.stdin, output: process.stdout });
let currentCase = "ADMISSION";
let oidcPhase = "not-started";

async function privateJson(path: string): Promise<unknown> {
  const info = await stat(path);
  contract(info.isFile() && (process.platform === "win32" || (info.mode & 0o077) === 0), "PRIVATE_MANIFEST_OR_CALLBACK_REQUIRED");
  return JSON.parse(await readFile(path, "utf8"));
}

async function check(name: string, action: () => Promise<void>) {
  currentCase = name;
  await action(); results.push({ case: name, passed: true });
  process.stdout.write("PASS " + name + "\n");
}

async function control(name: string, expiresAt?: number) {
  if (expiresAt !== undefined) contract(expiresAt > Date.now(), "AUTHORIZATION_TRANSACTION_EXPIRED");
  let answer: string;
  try {
    answer = await input.question("ROOT_CONTROL_REQUIRED " + name + " (type continue after actual owner action)\n",
      expiresAt === undefined ? {} : { signal: AbortSignal.timeout(expiresAt - Date.now()) });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw new Error("AUTHORIZATION_TRANSACTION_EXPIRED");
    throw error;
  }
  contract(answer.trim() === "continue", "OWNER_CONTROL_NOT_CONFIRMED");
}

async function rejectedOAuth(action: () => Promise<unknown>, errors: string[]) {
  let rejected = false;
  try { await action(); }
  catch (error) { rejected = error instanceof oidc.ResponseBodyError && errors.includes(error.error); }
  contract(rejected, "EXPECTED_SAFE_OAUTH_DENIAL");
}

async function run() {
  contract(process.argv.slice(2).length === 0 || docsOnly, "UNSUPPORTED_PILOT_MODE");
  const path = process.env.PARTNER_PILOTS_MANIFEST;
  contract(path && process.env.RUN_PARTNER_PILOTS === "1", "EXPLICIT_MANIFEST_AND_OPT_IN_REQUIRED");
  const manifest = assignedManifest(await privateJson(resolve(path)));
  authorizeSandbox(manifest.origin, process.env);
  contract(manifest.runId && manifest.sourceRevision && manifest.caFile && manifest.rental && manifest.operations && manifest.documents,
    "ASSIGNED_MANIFEST_REQUIRED");
  await mkdir(work, { recursive: true, mode: 0o700 });
  const transport = sandboxTransport(manifest.origin, await readFile(manifest.caFile, "utf8"), process.env, observations);
  if (!docsOnly) {
  const rentalConfig = await discover(manifest.origin, manifest.rental, transport);
  const rental = await machine(rentalConfig, manifest.rental);
  const rentalApp = new ReadApplication(manifest.origin, transport, rental.tokens.access_token);
  await check("RENTAL_READS_PAGING_TYPED_AND_TENANT_BOUNDARIES", () => rentalScenario(rentalApp, manifest.rental.vectors));
  if (manifest.rental.vectors.equipment) await check("APPROVED_ALL_PROFILE_OBEYS_EFFECTIVE_LOCATION_CEILING", async () => {
    await rentalApp.resourceBoundaries("equipment", manifest.rental.vectors.equipment!);
  });
  await check("MACHINE_SCOPE_ESCALATION_DENIED", () => rejectedOAuth(() => oidc.clientCredentialsGrant(rentalConfig, {
    grant_id: manifest.rental.grantId!, scope: manifest.rental.scopes.join(" ") + " documents:read",
  }), ["invalid_grant", "invalid_scope"]));
  await check("OTHER_CLIENT_GRANT_DENIED", () => rejectedOAuth(() => oidc.clientCredentialsGrant(rentalConfig, {
    grant_id: manifest.operations.grantId!, scope: manifest.rental.scopes.filter(scope => manifest.operations.scopes.includes(scope)).join(" "),
  }), ["invalid_grant", "invalid_scope"]));
  await check("TOKEN_REVOCATION_DENIES_NEXT_REQUEST", async () => {
    freshForControl(rental, 15);
    await oidc.tokenRevocation(rentalConfig, rental.tokens.access_token, { token_type_hint: "access_token" });
    await rentalApp.denied("/api/v1/objects", 401);
  });

  const operationsConfig = await discover(manifest.origin, manifest.operations, transport);
  const operations = await machine(operationsConfig, manifest.operations);
  const operationsApp = new ReadApplication(manifest.origin, transport, operations.tokens.access_token);
  await check("OPERATIONS_READS_EQUIPMENT_MONITORING_AND_BOUNDARIES", () => operationsScenario(operationsApp, manifest.operations.vectors));
  await check("CURRENT_INSTALLATION_BOUNDARY_NARROWS_NEXT_REQUEST", async () => {
    const before = manifest.operations.vectors.objects!.allowed;
    contract(manifest.operations.afterNarrowObjects.length > 0 && manifest.operations.afterNarrowObjects.length < before.length &&
      manifest.operations.afterNarrowObjects.every(id => before.includes(id)), "STRICT_SUBSET_BOUNDARY_REQUIRED");
    const oldCursor = await operationsApp.firstCursor("objects");
    freshForControl(operations, 30);
    await control("operations-narrow");
    freshForControl(operations, 1);
    await operationsApp.denied("/api/v1/objects?" + new URLSearchParams({ pageSize: "1", cursor: oldCursor }), 400);
    await operationsApp.list("objects", manifest.operations.afterNarrowObjects, 1);
    for (const id of manifest.operations.vectors.objects!.allowed.filter(id => !manifest.operations.afterNarrowObjects.includes(id))) {
      await operationsApp.denied(`/api/v1/objects/${encodeURIComponent(id)}/monitoring?days=90`, 404);
    }
  });

  const currentRental = await machine(rentalConfig, manifest.rental);
  await check("OWNER_GRANT_REVOKE_DENIES_NEXT_REQUEST_AND_REISSUE", async () => {
    freshForControl(currentRental, 30);
    await control("rental-grant-revoke");
    freshForControl(currentRental, 1);
    await new ReadApplication(manifest.origin, transport, currentRental.tokens.access_token).denied("/api/v1/objects", 401);
    await rejectedOAuth(() => machine(rentalConfig, manifest.rental), ["invalid_grant"]);
  });
  }

  currentCase = "COMPANY_OWNER_BROWSER_CONSENT";
  const docsConfig = await discover(manifest.origin, manifest.documents, transport, true);
  const request = await delegatedRequest(docsConfig, manifest.documents);
  const authorizeFile = resolve(work, "authorization.json"), callbackFile = resolve(work, "callback.json");
  await rm(callbackFile, { force: true });
  await writeFile(authorizeFile, JSON.stringify({ authorizeUrl: request.url.href, redirectUri: manifest.documents.redirectUri,
    callbackFile, expiresAt: request.createdAt + 5 * 60 * 1000 }), { mode: 0o600 });
  process.stdout.write("ROOT_BROWSER_REQUIRED private handoff file " + authorizeFile + "\n");
  // The browser consent itself authorizes exchange. A coordinator receipt is
  // evidence, not a second gate that can consume the provider's code lifetime.
  while (true) {
    contract(Date.now() < request.createdAt + 5 * 60 * 1000, "AUTHORIZATION_TRANSACTION_EXPIRED");
    try { await stat(callbackFile); break; }
    catch (error) {
      if (!(error && typeof error === "object" && "code" in error && error.code === "ENOENT")) throw error;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const callback = await privateJson(callbackFile) as { callbackUrl: string };
  await check("SDK_REJECTS_WRONG_STATE_BEFORE_TOKEN_REQUEST", async () => {
    const bad = new URL(callback.callbackUrl);
    bad.searchParams.set("state", "deliberately-wrong-state");
    const count = observations.length;
    let rejected = false;
    try { await oidc.authorizationCodeGrant(docsConfig, bad, { expectedState: request.state,
      expectedNonce: request.nonce, pkceCodeVerifier: request.verifier, idTokenExpected: true }); }
    catch { rejected = true; }
    contract(rejected && observations.length === count, "STATE_CHECK_MUST_PRECEDE_TOKEN_EXCHANGE");
  });
  currentCase = "REAL_CODE_PKCE_NONCE_SIGNATURE_AND_USERINFO";
  const docs = await delegatedExchange(docsConfig, manifest.documents, request, callback.callbackUrl,
    phase => { oidcPhase = phase; });
  await rm(callbackFile, { force: true }); await rm(authorizeFile, { force: true });
  const docsApp = new ReadApplication(manifest.origin, transport, docs.tokens.access_token);
  await check("REAL_CODE_PKCE_NONCE_SIGNATURE_AND_USERINFO", async () => { contract(docs.subject, "VALIDATED_USER_REQUIRED"); });
  await check("DOCS_METADATA_PAGING_AND_RESOURCE_BOUNDARIES", async () => {
    contract(manifest.documents.vectors.documents, "DOCUMENT_VECTORS_REQUIRED");
    await docsApp.resourceBoundaries("documents", manifest.documents.vectors.documents);
    for (const id of manifest.documents.vectors.documents.allowed) {
      const row = await docsApp.document(id);
      if (!manifest.documents.scopes.includes("objects:read")) contract(row.objectId === null, "IMPLICIT_OBJECT_LINK_AUTHORITY_FORBIDDEN");
      if (!manifest.documents.scopes.includes("counterparties:read")) contract(row.counterpartyId === null, "IMPLICIT_COUNTERPARTY_LINK_AUTHORITY_FORBIDDEN");
    }
  });
  await check("DOCUMENT_VERSION_EXACT_BINARY_AND_NATIVE_DENIALS", async () => {
    const allowed = manifest.documents.allowedContent;
    contract(manifest.documents.deniedContent.length >= 1, "NATIVE_FILE_DENIAL_FIXTURE_REQUIRED");
    await docsApp.content(allowed.docId, allowed.versionId, allowed.sha256);
    for (const value of manifest.documents.deniedContent) {
      await docsApp.denied(`/api/v1/documents/${encodeURIComponent(value.docId)}/versions/${encodeURIComponent(value.versionId)}/content`, 404);
    }
  });
  await check("ID_TOKEN_IS_NOT_API_CREDENTIAL", async () => {
    const idApp = new ReadApplication(manifest.origin, transport, docs.tokens.id_token!);
    await idApp.denied("/api/v1/documents", 401);
  });
  await check("CURRENT_USER_MEMBERSHIP_REVOKE_DENIES_NEXT_REQUEST", async () => {
    freshForControl(docs, 30);
    await control("documents-member-revoke");
    freshForControl(docs, 1);
    await docsApp.denied("/api/v1/documents", 401);
  });

  contract(observations.every(row => row.method === "GET" || (row.method === "POST" && ["/api/oauth2/token", "/api/oauth2/revoke"].includes(row.path))),
    "NO_BUSINESS_WRITE_REQUESTS_ALLOWED");
  return { runId: manifest.runId, sourceRevision: manifest.sourceRevision, phase: docsOnly ? "documents-only" : "all", results, observations,
    businessWriteRequests: 0, clientSource: "external-public-contract-only" };
}

try {
  const report = await run();
  await writeFile(resolve(work, resultFile), JSON.stringify(report, null, 2), { mode: 0o600 });
  process.stdout.write("SYNTHETIC_PILOTS_COMPLETE " + results.length + " cases; private evidence saved\n");
} catch (error) {
  const code = error && typeof error === "object" && "code" in error && typeof error.code === "string" && /^[A-Z0-9_]+$/.test(error.code) ? error.code :
    error instanceof Error && /^[A-Z0-9_]+$/.test(error.message) ? error.message : "CLIENT_CONTRACT_CHECK_FAILED";
  const safeName = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9_]+$/.test(value) ? value : "unknown";
  const diagnostic = { errorName: safeName(error instanceof Error ? error.name : undefined),
    causeName: safeName(error instanceof Error && error.cause instanceof Error ? error.cause.name : undefined),
    causeCode: error instanceof Error && error.cause instanceof Error && /^[A-Z0-9_]+$/.test(error.cause.message) ? error.cause.message : undefined, phase: oidcPhase };
  await mkdir(work, { recursive: true, mode: 0o700 });
  await writeFile(resolve(work, resultFile), JSON.stringify({ diagnostic, phase: docsOnly ? "documents-only" : "all", results, failedCase: currentCase, code,
    observations, httpAcceptance: "NOT_COMPLETE" }, null, 2), { mode: 0o600 });
  process.stderr.write("PILOT_NOT_COMPLETE " + currentCase + " " + code + " " + JSON.stringify(diagnostic) + "\n"); process.exitCode = 1;
} finally { input.close(); }
