import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { exportSchema, render, root, validateSchema } from "./generate.mjs";

const script = fileURLToPath(new URL("generate.mjs", import.meta.url));
const schema = JSON.parse(exportSchema());
const cli = (mode, file, env = {}) => spawnSync(process.execPath, [script, mode, "--output", file], {
  encoding: "utf8", env: { ...process.env, ...env },
});

test("network state is the eighteenth operation with complete fictional non-financial wire example", async () => {
  const operations = Object.entries(schema.paths).flatMap(([path, item]) =>
    Object.entries(item).filter(([, value]) => value?.operationId).map(([method, value]) => [method, path, value.operationId]));
  assert.equal(operations.length, 18);
  assert.equal(Object.keys(schema.paths).length, 17);
  assert.equal(operations.filter(([method]) => method === "get").length, 17);
  assert.deepEqual(operations.filter(([method]) => method === "post"), [["post", "/contracts", "createContract"]]);
  const operation = schema.paths["/monitoring/network-state"].get;
  assert.equal(operation.operationId, "getNetworkState");
  assert.deepEqual(operation.security, [
    { ProductOAuth: ["monitoring:read", "objects:read"] },
    { ProductServiceOAuth: ["monitoring:read", "objects:read"] },
  ]);
  const sample = operation.responses[200].content["application/json"].examples.fictional;
  assert.match(sample.summary, /Fictional/);
  assert.deepEqual(Object.keys(sample.value.items[0]).sort(), ["lastChargeAt", "mismatch", "objectId", "silentDays", "status"]);
  assert.deepEqual(Object.keys(sample.value.summary.byStatus).sort(),
    ["decommissioned", "disabled", "maintenance", "no_link", "not_working", "on_repair", "unknown", "working"]);
  assert.equal(sample.value.items[0].lastChargeAt, null);
  assert.equal(sample.value.context.dataThrough, null);
  assert.equal(sample.value.context.dataLagHours, null);
  assert.equal(sample.value.context.catalogMode, "current");
  assert.equal(sample.value.context.boundaryScope, "authorizedOperatedRegion");
  for (const mutate of [
    copy => { delete copy.paths["/monitoring/network-state"]; },
    copy => { copy.paths["/monitoring/network-state"].get.operationId = "inventedNetworkState"; },
    copy => { copy.paths["/monitoring/network-state"].post = copy.paths["/monitoring/network-state"].get; },
  ]) {
    const copy = structuredClone(schema);
    mutate(copy);
    assert.throws(() => validateSchema(copy), /operation manifest/);
  }
  const config = JSON.parse(await readFile(new URL("tsconfig.json", import.meta.url), "utf8"));
  assert.equal(config.files.length, 7);
  assert.equal(config.files.filter(file => file === "network-state-consumer.ts").length, 1);
});

test("offline schema exactly matches real database-module factory without startup or connection", () => {
  const actual = JSON.parse(exportSchema({ runtimeDatabase: true }));
  assert.deepEqual(actual, schema); // paths/components/required/security, plus all metadata
});

test("generation is deterministic; drift fails and does not overwrite output", async () => {
  const temporary = await mkdtemp(join(tmpdir(), "partner-wire-check-"));
  try {
    const first = join(temporary, "first.d.ts"), second = join(temporary, "second.d.ts");
    for (const file of [first, second]) {
      const result = cli("generate", file);
      assert.equal(result.status, 0, result.stderr);
    }
    assert.deepEqual(await readFile(first), await readFile(second));
    assert.equal(cli("check", first).status, 0);
    const drifted = (await readFile(first, "utf8")) + "\n// deliberate drift negative control\n";
    await writeFile(first, drifted);
    const result = cli("check", first);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /wire types drift/);
    assert.equal(await readFile(first, "utf8"), drifted);
    // Export/generator failure must not silently keep stale output as success.
    const failed = cli("generate", first, { PARTNER_OPENAPI_PYTHON: join(temporary, "missing-python") });
    assert.notEqual(failed.status, 0);
    assert.equal(await readFile(first, "utf8"), drifted);
  } finally { await rm(temporary, { recursive: true, force: true }); }
});

test("unknown versions, unresolved refs and remote refs fail before generation", async () => {
  for (const mutate of [
    copy => { copy.openapi = "2.0"; },
    copy => { copy.components.schemas.Object.properties.id.$ref = "#/components/schemas/Unregistered"; },
    copy => { copy.components.schemas.Object.properties.id.$ref = "https://forbidden.example.invalid/schema"; },
  ]) {
    const copy = structuredClone(schema);
    mutate(copy);
    await assert.rejects(render(copy));
  }
});

test("official structural validator rejects unknown schema types", async () => {
  const copy = structuredClone(schema);
  copy.components.schemas.Object.type = "not-a-json-schema-type";
  await assert.rejects(render(copy));
});

test("real official generator validation errors propagate", async () => {
  const copy = structuredClone(schema);
  copy.paths["/objects"].get.parameters.push({ name: "bad", in: "invented", schema: { type: "string" } });
  await assert.rejects(render(copy));
});

test("offline exporter blocks runtime imports, environment files and sockets", () => {
  const python = process.env.PARTNER_OPENAPI_PYTHON || fileURLToPath(new URL("../../../.venv/bin/python", import.meta.url));
  const code = `
import importlib, runpy, socket, sys
module = runpy.run_path(sys.argv[1])
schema = module['export_schema']()
assert schema['openapi'] == '3.1.0'
assert not {'app.main','app.config','app.auth','app.services.partner_identity'} & sys.modules.keys()
for action in (
    lambda: importlib.import_module('app.config'),
    lambda: getattr(sys.modules['app.database'], 'engine'),
    lambda: open('/synthetic-offline-schema/.env'),
    lambda: socket.create_connection(('127.0.0.1', 1)),
):
    try: action()
    except RuntimeError: pass
    else: raise AssertionError('Offline boundary was bypassed')
`;
  const result = spawnSync(python, ["-c", code, join(root, "scripts/export-partner-openapi.py")], {
    encoding: "utf8", env: { LANG: "C.UTF-8", PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.equal(result.status, 0, result.stderr);
});
