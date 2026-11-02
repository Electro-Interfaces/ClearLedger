/** Root-authorized loopback callback reservation; no outgoing HTTP or OAuth. */
import https from "node:https";
import { readFile, writeFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { callbackUrl, loopbackOrigin } from "./guards.ts";

if (process.env.RUN_PARTNER_CALLBACK !== "1") throw new Error("EXPLICIT_CALLBACK_RESERVATION_REQUIRED");

type Setup = { certFile: string; keyFile: string; redirectUri: string; callbackFile: string };
let setup: Setup | undefined;
const server = https.createServer({ minVersion: "TLSv1.2" }, (request, response) => {
  void (async () => {
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Referrer-Policy", "no-referrer");
    response.setHeader("Content-Security-Policy", "default-src 'none'");
    if (!setup || request.method !== "GET" || !request.url || request.url.length > 8192) {
      response.writeHead(404); response.end("Not found"); return;
    }
    // This application never accepts Core credentials on the callback boundary.
    if (request.headers.authorization || request.headers.cookie) {
      response.writeHead(400); response.end("Credentials must not be forwarded to the partner callback"); return;
    }
    const url = callbackUrl(new URL(request.url, setup.redirectUri).href, setup.redirectUri);
    await writeFile(setup.callbackFile, JSON.stringify({ callbackUrl: url.href, receivedAt: Date.now() }), { flag: "wx", mode: 0o600 });
    response.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Authorization callback received. Return to the synthetic client runner.");
    process.stdout.write("CALLBACK_RECEIVED\n");
  })().catch(() => { response.writeHead(400); response.end("Callback rejected"); process.stdout.write("CALLBACK_REJECTED\n"); });
});
const requestedPort = Number(process.env.PARTNER_CALLBACK_PORT || "0");
const requestedHost = process.env.PARTNER_CALLBACK_HOST || "127.0.0.1";
if (!Number.isInteger(requestedPort) || requestedPort < 0 || requestedPort > 65535) throw new Error("INVALID_CALLBACK_PORT");
if (!["127.0.0.1", "127.0.0.2"].includes(requestedHost)) throw new Error("INVALID_CALLBACK_HOST");
server.listen(requestedPort, requestedHost, () => {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("CALLBACK_RESERVATION_FAILED");
  process.stdout.write(`CALLBACK_RESERVED https://${requestedHost}:${address.port}/callback\n`);
});
server.on("tlsClientError", () => process.stdout.write("CALLBACK_TLS_NOT_READY_OR_UNTRUSTED\n"));
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", line => {
  void (async () => {
    if (line === "close") { server.close(); input.close(); return; }
    const value = JSON.parse(line) as Setup;
    const url = new URL(value.redirectUri);
    loopbackOrigin(url.origin);
    const address = server.address();
    if (!address || typeof address === "string" || url.hostname !== requestedHost || url.port !== String(address.port) || url.pathname !== "/callback" || url.search || url.hash) {
      throw new Error("RESERVED_CALLBACK_URI_REQUIRED");
    }
    server.setSecureContext({ cert: await readFile(value.certFile), key: await readFile(value.keyFile), minVersion: "TLSv1.2" });
    setup = value;
    process.stdout.write("CALLBACK_TLS_READY\n");
  })().catch(() => process.stdout.write("CALLBACK_SETUP_REJECTED\n"));
});
