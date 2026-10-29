import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile, mkdir, mkdtemp, rename, rm } from "node:fs/promises";
import { existsSync, lstatSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { createConfig } from "@redocly/openapi-core";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";

export const root = fileURLToPath(new URL("../../", import.meta.url));
const version = "7.10.1";
const operationIds = new Set(["listObjects", "getObject", "getObjectMonitoring", "listEquipment", "getEquipment",
  "listCounterparties", "getCounterparty", "listContracts", "getContract", "listDocuments", "getDocument", "downloadDocumentVersion"]);

// Schema generation is local. A future accidental remote resolver fails closed.
const noNetwork = () => { throw new Error("Network is forbidden during offline wire type generation"); };
globalThis.fetch = noNetwork;
http.request = http.get = https.request = https.get = noNetwork;
net.Socket.prototype.connect = noNetwork;

export function validateSchema(schema) {
  if (schema?.openapi !== "3.1.0" || !schema.paths || !schema.components?.schemas) {
    throw new Error("Expected curated OpenAPI 3.1.0 with paths and components");
  }
  if (schema.servers?.length !== 1 || schema.servers[0].url !== "https://partner-schema.example.invalid/api/v1") {
    throw new Error("Only the synthetic offline schema server is accepted");
  }
  const operations = [];
  for (const item of Object.values(schema.paths)) {
    for (const [method, operation] of Object.entries(item)) {
      if (["get", "post", "put", "patch", "delete", "options", "head", "trace"].includes(method)) {
        if (method !== "get" || operation["x-elsy-readiness"] !== "candidate") throw new Error("Expected candidate GET operations");
        operations.push(operation.operationId);
      }
    }
  }
  if (operations.length !== 12 || new Set(operations).size !== 12 || operations.some(id => !operationIds.has(id))) {
    throw new Error("Unexpected curated product operation manifest");
  }
  function refs(value) {
    if (!value || typeof value !== "object") return;
    if (Object.hasOwn(value, "$ref")) {
      if (typeof value.$ref !== "string" || !value.$ref.startsWith("#/")) throw new Error("Only local schema refs are accepted");
      let target = schema;
      for (const part of value.$ref.slice(2).split("/")) {
        const key = part.replaceAll("~1", "/").replaceAll("~0", "~");
        if (!target || !Object.hasOwn(target, key)) throw new Error("Unresolved local schema ref");
        target = target[key];
      }
    }
    for (const child of Object.values(value)) refs(child);
  }
  refs(schema);
}

export function exportSchema({ runtimeDatabase = false } = {}) {
  const python = process.env.PARTNER_OPENAPI_PYTHON || fileURLToPath(new URL("../../../.venv/bin/python", import.meta.url));
  return execFileSync(python, [join(root, "scripts/export-partner-openapi.py"), ...(runtimeDatabase ? ["--runtime-database"] : [])], {
    cwd: tmpdir(), encoding: "utf8", maxBuffer: 4 * 1024 * 1024,
    env: { LANG: "C.UTF-8", PYTHONDONTWRITEBYTECODE: "1", ...(process.env.SystemRoot ? { SystemRoot: process.env.SystemRoot } : {}) },
  });
}

export async function render(schema, schemaText = JSON.stringify(schema)) {
  validateSchema(schema);
  const installed = JSON.parse(await readFile(new URL("node_modules/openapi-typescript/package.json", import.meta.url), "utf8"));
  if (installed.version !== version) throw new Error("Generator version differs from pinned " + version);
  // Explicit official validator rules: the Node API's default configuration
  // only guarantees operationId uniqueness, not strict structural validation.
  const redocly = await createConfig({ rules: {
    struct: "error", "operation-operationId-unique": "error", "no-unresolved-refs": "error",
  } });
  const ast = await openapiTS(schema, { redocly, alphabetize: true, defaultNonNullable: false });
  const sha = createHash("sha256").update(schemaText).digest("hex");
  return COMMENT_HEADER + `// openapi-typescript ${version}; curated schema sha256: ${sha}\n` + astToString(ast);
}

export async function main(args = process.argv.slice(2)) {
  const [mode = "generate", ...options] = args;
  if (!["generate", "check"].includes(mode) || (options.length && (options.length !== 2 || options[0] !== "--output"))) {
    throw new Error("Usage: generate.mjs generate|check [--output file]");
  }
  const modules = new URL("node_modules", import.meta.url);
  if (existsSync(modules) && lstatSync(modules).isSymbolicLink()) throw new Error("Use an owned tool node_modules directory");
  const output = options.length ? resolve(options[1]) : join(root, "src/generated/partner-api.d.ts");
  const temporary = await mkdtemp(join(tmpdir(), "partner-wire-types-"));
  try {
    const source = exportSchema();
    const content = await render(JSON.parse(source), source);
    const generated = join(temporary, "partner-api.d.ts");
    await writeFile(generated, content);
    const bytes = await readFile(generated);
    if (mode === "check") {
      if (!bytes.equals(await readFile(output))) throw new Error("Partner wire types drift: run npm run partner:types");
      process.stdout.write("Partner wire types match the current curated schema\n");
    } else {
      await mkdir(dirname(output), { recursive: true });
      const staging = output + `.${process.pid}.tmp`;
      try {
        await writeFile(staging, bytes);
        await rename(staging, output);
      } finally { await rm(staging, { force: true }); }
      process.stdout.write("Generated partner wire types from 12 curated candidate operations\n");
    }
  } finally { await rm(temporary, { recursive: true, force: true }); }
}

if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) {
  main().catch(error => { process.stderr.write(error.message + "\n"); process.exitCode = 1; });
}
