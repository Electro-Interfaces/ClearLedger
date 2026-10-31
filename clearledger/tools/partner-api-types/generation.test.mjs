import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { exportSchema, render, root } from "./generate.mjs";

const script = fileURLToPath(new URL("generate.mjs", import.meta.url));
const schema = JSON.parse(exportSchema());
const cli = (mode, file, env = {}) => spawnSync(process.execPath, [script, mode, "--output", file], {
  encoding: "utf8", env: { ...process.env, ...env },
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
