import https from "node:https";
import type { LookupFunction } from "node:net";
import type { CustomFetch } from "openid-client";
import { authorizeRequest, authorizeSandbox } from "./guards.ts";
import type { PilotEnvironment } from "./guards.ts";

export type Observation = { method: string; path: string; status: number; requestId: string | null };

/** Fetch treats null and undefined as an absent body, including UserInfo GET. */
export function protocolBody(body: unknown): string | URLSearchParams | undefined {
  if (body === null || body === undefined) return undefined;
  if (typeof body === "string" || body instanceof URLSearchParams) return body;
  throw new Error("UNSUPPORTED_PROTOCOL_BODY");
}

/** External test application transport, isolated from all Core UI transports. */
export function sandboxTransport(origin: string, ca: string, env: PilotEnvironment, observations: Observation[]) {
  authorizeSandbox(origin, env);
  if (!ca.includes("BEGIN CERTIFICATE")) throw new Error("ASSIGNED_SANDBOX_CA_REQUIRED");
  async function request(input: string | URL, options: {
    method?: string; headers?: HeadersInit; body?: string | URLSearchParams; signal?: AbortSignal;
  } = {}): Promise<Response> {
    const method = options.method || "GET";
    const url = authorizeRequest(origin, input, method, env);
    const headers = new Headers(options.headers);
    headers.set("accept-encoding", "identity");
    const body = options.body === undefined ? undefined : Buffer.from(options.body.toString(), "utf8");
    if (body && body.byteLength > 16384) throw new Error("PROTOCOL_REQUEST_TOO_LARGE");
    if (body) headers.set("content-length", String(body.byteLength));
    return new Promise((resolve, reject) => {
      const signal = options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000);
      const loopbackLookup: LookupFunction = (hostname, options, callback) => {
        if (hostname !== "localhost") return callback(new Error("NON_LOOPBACK_DNS_DENIED"), "", 4);
        if (options.all) callback(null, [{ address: "127.0.0.1", family: 4 }]);
        else callback(null, "127.0.0.1", 4);
      };
      const req = https.request(url, { method, headers: Object.fromEntries(headers), ca, rejectUnauthorized: true,
        signal, agent: false, lookup: loopbackLookup }, response => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on("data", (part: Buffer) => {
          size += part.length;
          if (size > 8 * 1024 * 1024) response.destroy(new Error("SANDBOX_RESPONSE_TOO_LARGE"));
          else chunks.push(part);
        });
        response.on("error", () => reject(new Error("SANDBOX_RESPONSE_FAILED")));
        response.on("end", () => {
          const responseHeaders = new Headers();
          for (const [name, value] of Object.entries(response.headers)) {
            if (value !== undefined) responseHeaders.set(name, Array.isArray(value) ? value.join(", ") : value);
          }
          const status = response.statusCode || 0;
          observations.push({ method, path: url.pathname, status, requestId: responseHeaders.get("x-request-id") });
          const payload = [204, 205, 304].includes(status) ? null : Buffer.concat(chunks);
          resolve(new Response(payload, { status, headers: responseHeaders }));
        });
      });
      req.on("error", () => reject(new Error("SANDBOX_HTTPS_REQUEST_FAILED")));
      req.end(body);
    });
  }
  const customFetch: CustomFetch = (input, options) => {
    return request(input, { method: options.method, headers: options.headers, body: protocolBody(options.body), signal: options.signal });
  };
  return { request, customFetch };
}
