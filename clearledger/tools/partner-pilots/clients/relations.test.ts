import assert from "node:assert/strict";
import test from "node:test";
import { ReadApplication, relationPages, rentalRelationsScenario, documentRelationsScenario,
  requireDocumentRelationAuthority } from "./scenarios.ts";
import type { ContractWire, ContractTypeWire, ContractObjectsWire, ContractDocumentsWire, FilteredContractsWire,
  RentalRelations, DocumentRelations, RelationAuthority } from "./scenarios.ts";
import type { components } from "../../../src/generated/partner-api.d.ts";

// NOTRUN proposal: pure scripted typed mocks, no OAuth, SDK initialization, server,
// sandboxTransport invocation, HTTP, database, file, control or pilot evidence.
const origin = "https://example.invalid";
const c0: ContractWire = { id: "50000000-0000-4000-8000-000000000001", number: "SYN-0", date: "2026-10-29",
  title: null, counterpartyId: null, isClosed: false, scopeType: "locations", typeCode: " Pilot Unknown Ё ", validUntil: "31.12.2030" };
const c1: ContractWire = { ...c0, id: "50000000-0000-4000-8000-000000000002", number: "SYN-1", typeCode: "", validUntil: null };
const hidden = "50000000-0000-4000-8000-000000000003", foreign = "50000000-0000-4000-8000-000000000004";
const p0 = "pilot-object-0", p1 = " Точка Ё pilot ";
const d0 = "60000000-0000-4000-8000-000000000001", d1 = "60000000-0000-4000-8000-000000000003";
const opaque = "opaque+/= Ё";
const metadata: ContractTypeWire = { typeCode: c0.typeCode!, label: null, gkBasis: null, direction: null, isActive: null };
const rental: RentalRelations = { contracts: [
  { expected: c0, metadata, objects: { contractId: c0.id, scopeType: "locations", allowed: [p0, p1], hidden: ["pilot-object-2", "pilot-foreign-object"] } },
  { expected: c1, metadata: null, objects: { contractId: c1.id, scopeType: "locations", allowed: [p1], hidden: [] } },
], hiddenParents: [hidden], foreignParents: [foreign] };
const documents: DocumentRelations = { contracts: [
  { contractId: c0.id, allowed: [d0, d1], hidden: ["private-doc", "foreign-doc", "ungranted-doc"] },
  { contractId: c1.id, allowed: [], hidden: [] },
], hiddenParents: [hidden], foreignParents: [foreign] };
const grant = { mode: "SET", ids: [c0.id, c1.id] };
const authority: RelationAuthority = { scopes: ["contracts:read", "documents:read"],
  resourceScopes: { contracts: grant, documents: { mode: "SET", ids: [d0, d1] } } };
type Wire = ContractWire | ContractTypeWire | ContractObjectsWire | ContractDocumentsWire |
  FilteredContractsWire | components["schemas"]["Problem"];
type Step = { path: string; body: Wire; status?: number };
function problem(status: 400 | 403 | 404 | 422): components["schemas"]["Problem"] {
  const codes = { 400: "invalid_cursor", 403: "access_denied", 404: "not_found", 422: "invalid_request" };
  return { title: "Synthetic", detail: "Synthetic only", status, code: codes[status], requestId: "synthetic-request" };
}
function relationsPath(id: string, resource: "objects" | "documents", query: Record<string, string> = {}): string {
  return `/api/v1/contracts/${encodeURIComponent(id)}/${resource}?` + new URLSearchParams({ pageSize: "1", ...query });
}
function deny(path: string, status: 400 | 403 | 404 | 422): Step { return { path, status, body: problem(status) }; }
function scripted(steps: Step[]) {
  const pending = [...steps], observed: string[] = [];
  const transport: ReadApplication["transport"] = {
    request: async (input, options = {}) => {
      assert.equal(options.method ?? "GET", "GET");
      assert.equal(new Headers(options.headers).get("authorization"), "Bearer pure-mock-token");
      const url = new URL(input), path = url.pathname + url.search;
      assert.equal(url.origin, origin);
      const step = pending.shift(); assert.ok(step, "Unexpected request: " + path);
      assert.equal(path, step.path); observed.push(path);
      return new Response(JSON.stringify(step.body), { status: step.status ?? 200, headers: {
        "cache-control": "no-store", "content-type": step.status ? "application/problem+json" : "application/json",
      } });
    },
    customFetch: async () => { throw new Error("OAUTH_FORBIDDEN_IN_PURE_MOCK"); },
  };
  return { app: new ReadApplication(origin, transport, "pure-mock-token"), observed,
    done: () => assert.equal(pending.length, 0, "Unconsumed scripted response") };
}
function objectPage(ids: string[], cursor: string | null, contractId = c0.id): ContractObjectsWire {
  return { contractId, scopeType: "locations", items: ids.map(objectId => ({ objectId })), total: 2, nextCursor: cursor };
}
function documentPage(ids: string[], cursor: string | null, contractId = c0.id): ContractDocumentsWire {
  return { contractId, items: ids.map(documentId => ({ documentId })), total: 2, nextCursor: cursor };
}
function cursorDenials(id: string, resource: "objects" | "documents"): Step[] {
  return [deny(relationsPath(id, resource, { q: "synthetic" }), 422),
    deny(relationsPath(id, resource, { cursor: opaque, pageSize: "2" }), 400),
    deny(relationsPath(c1.id, resource, { cursor: opaque }), 400)];
}

test("NOTRUN rental flow consumes typed metadata/objects and preserves exact raw values", async () => {
  const firstList: FilteredContractsWire = { items: [c0], total: 2, nextCursor: opaque };
  const exactList: FilteredContractsWire = { items: [c0], total: 1, nextCursor: null };
  const mock = scripted([
    { path: `/api/v1/contracts/${c0.id}`, body: c0 },
    { path: "/api/v1/contract-types?" + new URLSearchParams({ typeCode: c0.typeCode! }), body: metadata },
    { path: "/api/v1/contracts?" + new URLSearchParams({ pageSize: "1", typeCode: c0.typeCode! }), body: exactList },
    { path: relationsPath(c0.id, "objects"), body: objectPage([p0], opaque) },
    { path: relationsPath(c0.id, "objects", { cursor: opaque }), body: objectPage([p1], null) },
    ...cursorDenials(c0.id, "objects"), deny(relationsPath(c0.id, "documents"), 403),
    { path: `/api/v1/contracts/${c1.id}`, body: c1 },
    { path: relationsPath(c1.id, "objects"), body: { ...objectPage([p1], null, c1.id), total: 1 } },
    deny(relationsPath(c1.id, "objects", { q: "synthetic" }), 422), deny(relationsPath(c1.id, "documents"), 403),
    ...[hidden, foreign].flatMap(id => [deny(relationsPath(id, "objects"), 404), deny(relationsPath(id, "documents"), 403)]),
    { path: "/api/v1/contracts?pageSize=1", body: firstList },
    deny("/api/v1/contracts?" + new URLSearchParams({ pageSize: "1", cursor: opaque, typeCode: "different synthetic type" }), 400),
    deny("/api/v1/contracts?" + new URLSearchParams({ pageSize: "1", cursor: opaque, q: "changed synthetic filter" }), 400),
  ]);
  await rentalRelationsScenario(mock.app, rental); mock.done();
  assert.equal(mock.observed.filter(path => path.startsWith("/api/v1/contract-types?")).length, 1); // empty type not queried
});

test("NOTRUN delegated document flow uses independent effective children; terminal null ends without another read", async () => {
  requireDocumentRelationAuthority(authority);
  const mock = scripted([
    { path: relationsPath(c0.id, "documents"), body: documentPage([d0], opaque) },
    { path: relationsPath(c0.id, "documents", { cursor: opaque }), body: documentPage([d1], null) },
    ...cursorDenials(c0.id, "documents"),
    { path: relationsPath(c1.id, "documents"), body: { ...documentPage([], null, c1.id), total: 0 } },
    deny(relationsPath(c1.id, "documents", { q: "synthetic" }), 422),
    ...[hidden, foreign].map(id => deny(relationsPath(id, "documents"), 404)),
  ]);
  await documentRelationsScenario(mock.app, documents); mock.done();
  assert.ok(mock.observed.every(path => !path.includes("/versions/")), "relation IDs confer no file authority");
});

test("NOTRUN current document profile and each missing scope/grant fail closed independently", () => {
  const missing: RelationAuthority[] = [
    { scopes: ["openid", "documents:read", "documents.files:download"], resourceScopes: { ...authority.resourceScopes, contracts: { mode: "EMPTY", ids: [] } } },
    { ...authority, scopes: ["documents:read"] }, { ...authority, scopes: ["contracts:read"] },
    { ...authority, resourceScopes: { ...authority.resourceScopes, contracts: { mode: "EMPTY", ids: [] } } },
    { ...authority, resourceScopes: { ...authority.resourceScopes, documents: { mode: "EMPTY", ids: [] } } },
    { ...authority, resourceScopes: { ...authority.resourceScopes, contracts: { mode: "SET", ids: [] } } },
  ];
  for (const value of missing) assert.throws(() => requireDocumentRelationAuthority(value), /DOCUMENT_RELATIONS_BLOCKED_BY_PROFILE/);
  assert.doesNotThrow(() => requireDocumentRelationAuthority(authority));
});

test("NOTRUN independent scope/grant denial is a scripted expected403, not a server ACL test", async () => {
  const mock = scripted(Array.from({ length: 4 }, () => deny(relationsPath(c0.id, "documents"), 403)));
  for (let i = 0; i < 4; i++) await mock.app.denied(relationsPath(c0.id, "documents"), 403);
  mock.done();
});

test("NOTRUN walker rejects duplicated IDs even if subject/graph would repeat them", async () => {
  const pages = [documentPage([d0], opaque), documentPage([d0], null)];
  await assert.rejects(() => relationPages(async () => { const page = pages.shift(); assert.ok(page); return page; },
    documents.contracts[0]!, page => page.items.map(item => item.documentId)), /DUPLICATE_RELATION_ACROSS_PAGES/);
});

test("NOTRUN walker rejects hidden child and globally counted total", async () => {
  for (const page of [documentPage(["private-doc"], opaque), { ...documentPage([d0], opaque), total: 5 }]) {
    await assert.rejects(() => relationPages(async () => page, documents.contracts[0]!,
      value => value.items.map(item => item.documentId)), /INDEPENDENTLY_HIDDEN_RELATION_DISCLOSED|RELATION_PAGE_SHAPE/);
  }
});

test("NOTRUN walker rejects wrong parent, premature null, repeated cursor and empty nonterminal page", async () => {
  const scripts = [ [objectPage([p0], opaque, c1.id)], [objectPage([p0], null)],
    [objectPage([p0], opaque), objectPage([p1], opaque)], [objectPage([], opaque)] ];
  for (const pages of scripts) await assert.rejects(() => relationPages(async () => {
    const page = pages.shift(); assert.ok(page); return page;
  }, rental.contracts[0]!.objects, page => page.items.map(item => item.objectId)),
  /RELATION_PARENT_MISMATCH|RELATION_SET_MISMATCH|RELATION_CURSOR_REPEATED_OR_EMPTY_PAGE/);
});

test("NOTRUN native company scope has no explicit object expansion", async () => {
  const vector = { contractId: c0.id, allowed: [], hidden: [p0, p1] };
  const page: ContractObjectsWire = { contractId: c0.id, scopeType: "company", items: [], total: 0, nextCursor: null };
  assert.equal(await relationPages(async () => page, vector, value => value.items.map(item => item.objectId),
    value => assert.equal(value.scopeType, "company")), null);
});

test("NOTRUN unknown type null metadata and raw validUntil cannot be guessed or normalized", async () => {
  for (const changed of [{ ...c0, typeCode: "lease" }, { ...c0, validUntil: "2030-12-31" }]) {
    const mock = scripted([{ path: `/api/v1/contracts/${c0.id}`, body: changed }]);
    await assert.rejects(() => rentalRelationsScenario(mock.app, rental), /RAW_CONTRACT_DETAIL_EXPECTATION_MISMATCH/); mock.done();
  }
  const mock = scripted([{ path: `/api/v1/contracts/${c0.id}`, body: c0 },
    { path: "/api/v1/contract-types?" + new URLSearchParams({ typeCode: c0.typeCode! }), body: { ...metadata, label: "Guessed label" } }]);
  await assert.rejects(() => rentalRelationsScenario(mock.app, rental), /RAW_TYPE_METADATA_MISMATCH/); mock.done();
});
