import assert from "node:assert/strict";
import test from "node:test";
import { protocolBody } from "./transport.ts";
import { authorizeRequest, authorizeSandbox, callbackUrl, loopbackOrigin } from "./guards.ts";

// These are pure URL/intent checks, not permission to contact these test URLs.
const origin = "https://127.0.0.1:1";
const env = { RUN_PARTNER_PILOTS: "1", PARTNER_PILOTS_ORIGIN: origin };

test("no opt-in, no assigned origin, no TLS bypass", () => {
  for (const input of [{}, { RUN_PARTNER_PILOTS: "1" }, { ...env, RUN_PARTNER_PILOTS: "0" },
    { ...env, NODE_TLS_REJECT_UNAUTHORIZED: "0" }, { ...env, PARTNER_PILOTS_ORIGIN: "https://127.0.0.1:2" }]) {
    assert.throws(() => authorizeSandbox(origin, input));
  }
});
test("exact loopback HTTPS only, no credentials/query/path/canonicalization shortcuts", () => {
  for (const value of ["http://127.0.0.1:1", "https://example.invalid", "https://10.10.70.53",
    "https://user:secret@127.0.0.1:1", origin + "/", origin + "?x=1", origin + "#x", "https://127.1:1"]) {
    assert.throws(() => loopbackOrigin(value));
  }
  assert.equal(loopbackOrigin("https://[::1]:1"), "https://[::1]:1");
});
test("partner reads and protocol writes only, cross-origin and business writes denied", () => {
  for (const [method, path] of [["GET", "/api/v1/objects"], ["GET", "/api/v1/objects/id/monitoring"],
    ["GET", "/api/v1/documents/id/versions/id/content"], ["POST", "/api/oauth2/token"], ["POST", "/api/oauth2/revoke"]]) {
    assert.equal(authorizeRequest(origin, origin + path, method!, env).origin, origin);
  }
  for (const [method, path] of [["POST", "/api/v1/contracts"], ["DELETE", "/api/v1/objects/id"],
    ["PATCH", "/api/references/counterparties/id"], ["POST", "/api/developer/clients"],
    ["POST", "/api/oauth2/token?grant_type=client_credentials"], ["GET", "/api/files/id"]]) {
    assert.throws(() => authorizeRequest(origin, origin + path, method!, env));
  }
  assert.throws(() => authorizeRequest(origin, "https://127.0.0.1:2/api/v1/objects", "GET", env));
  assert.throws(() => authorizeRequest(origin, "https://127.0.0.2:1/api/v1/objects", "GET", env));
});
test("callback must retain exact registered origin/path; SDK still validates state/nonce", () => {
  assert.equal(callbackUrl(origin + "/callback?code=synthetic&state=synthetic", origin + "/callback").pathname, "/callback");
  for (const value of ["https://example.invalid/callback", origin + "/other?code=synthetic", origin + "/callback#fragment"]) {
    assert.throws(() => callbackUrl(value, origin + "/callback"));
  }
});

test("Fetch null body is absent; unsupported protocol payloads fail before I/O", () => {
  assert.equal(protocolBody(null), undefined);
  assert.equal(protocolBody(undefined), undefined);
  assert.equal(protocolBody(""), "");
  const form = new URLSearchParams({ grant_type: "synthetic" });
  assert.equal(protocolBody(form), form);
  assert.throws(() => protocolBody({ token: "synthetic" }));
  assert.throws(() => protocolBody(new Uint8Array([1])));
});
