import { createHash } from "node:crypto";
import type { components, operations } from "../../../src/generated/partner-api.d.ts";
import type { sandboxTransport } from "./transport.ts";

export type Resource = "objects" | "equipment" | "counterparties" | "contracts" | "documents";
export type ObjectWire = components["schemas"]["Object"];
export type ContractWire = components["schemas"]["Contract"];
export type MonitoringWire = operations["getObjectMonitoring"]["responses"][200]["content"]["application/json"];
export type DocumentWire = operations["getDocument"]["responses"][200]["content"]["application/json"];
export type ContractTypeWire = operations["getContractTypeMetadata"]["responses"][200]["content"]["application/json"];
export type ContractObjectsWire = operations["listContractObjects"]["responses"][200]["content"]["application/json"];
export type ContractDocumentsWire = operations["listContractDocuments"]["responses"][200]["content"]["application/json"];
// Scenario expectations only: wire projections come from generated operations.
export type RelationVector = { contractId: string; allowed: string[]; hidden: string[] };
export type RentalRelations = {
  contracts: { expected: ContractWire; metadata: ContractTypeWire | null;
    objects: RelationVector & { scopeType: string } }[];
  hiddenParents: string[]; foreignParents: string[];
};
export type DocumentRelations = { contracts: RelationVector[]; hiddenParents: string[]; foreignParents: string[] };
export type RelationAuthority = { scopes: string[];
  resourceScopes?: Partial<Record<Resource, { mode?: string; ids?: string[] }>> };
export type FilteredContractsWire = operations["listContracts"]["responses"][200]["content"]["application/json"];
export type Vector = { mode: "ALL" | "SET"; allowed: string[]; foreign: string[]; ungranted: string[] };
export type Vectors = Partial<Record<Resource, Vector>>;
export type Result = { case: string; passed: boolean; details?: Record<string, string | number | boolean> };
type Transport = ReturnType<typeof sandboxTransport>;

export function contract(condition: unknown, code: string): asserts condition {
  if (!condition) throw new Error(code);
}

/** Tokens remain local variables in the external process, never a Core store. */
export class ReadApplication {
  readonly origin: string;
  readonly transport: Transport;
  readonly accessToken: string;
  constructor(origin: string, transport: Transport, accessToken: string) {
    this.origin = origin; this.transport = transport; this.accessToken = accessToken;
  }
  async get(path: string): Promise<Response> {
    return this.transport.request(new URL(path, this.origin), { headers: {
      Authorization: "Bearer " + this.accessToken, Accept: "application/json",
    } });
  }
  async denied(path: string, status: 400 | 401 | 403 | 404 | 422): Promise<void> {
    const response = await this.get(path);
    contract(response.status === status, "UNEXPECTED_DENIAL_STATUS");
    contract(response.headers.get("content-type")?.startsWith("application/problem+json"), "PROBLEM_DETAILS_REQUIRED");
    const value = await response.json() as Record<string, unknown>;
    contract(value.status === status && typeof value.code === "string" && typeof value.requestId === "string", "INVALID_SAFE_PROBLEM");
    contract(response.headers.get("cache-control")?.includes("no-store"), "NO_STORE_REQUIRED");
  }
  async firstCursor(resource: Resource): Promise<string> {
    const response = await this.get(`/api/v1/${resource}?pageSize=1`);
    contract(response.status === 200, "CURSOR_START_READ_FAILED");
    const value = await response.json() as { nextCursor?: unknown };
    contract(typeof value.nextCursor === "string", "MULTIPAGE_CURSOR_REQUIRED");
    return value.nextCursor;
  }
  async detail(resource: Resource, id: string): Promise<Record<string, unknown>> {
    const response = await this.get(`/api/v1/${resource}/${encodeURIComponent(id)}`);
    contract(response.status === 200, "AUTHORIZED_DETAIL_FAILED");
    const row = await response.json() as Record<string, unknown>;
    contract(row.id === id, "DETAIL_OPAQUE_ID_MISMATCH");
    if (resource === "objects") contract(row.level === "servicePoint", "SERVICE_POINT_LEVEL_REQUIRED");
    if (resource === "equipment") contract(row.level === "station", "STATION_LEVEL_REQUIRED");
    return row;
  }
  async list(resource: Resource, expected: string[], pageSize = 1): Promise<Record<string, unknown>[]> {
    const ids = new Set<string>(), cursors = new Set<string>(), rows: Record<string, unknown>[] = [];
    let cursor: string | null = null;
    for (let page = 0; page < 100; page++) {
      const url = new URL("/api/v1/" + resource, this.origin);
      url.searchParams.set("pageSize", String(pageSize));
      if (cursor !== null) url.searchParams.set("cursor", cursor);
      const response = await this.get(url.pathname + url.search);
      contract(response.status === 200, "READ_PAGE_FAILED");
      contract(response.headers.get("cache-control")?.includes("no-store"), "NO_STORE_REQUIRED");
      const value = await response.json() as Record<string, unknown>;
      contract(Array.isArray(value.items) && value.total === expected.length, "SCOPED_TOTAL_MISMATCH");
      contract(value.items.length <= pageSize && (value.nextCursor === null || typeof value.nextCursor === "string"), "INVALID_PAGE_SHAPE");
      for (const item of value.items) {
        contract(item && typeof item === "object" && typeof item.id === "string", "OPAQUE_ID_REQUIRED");
        contract(!ids.has(item.id), "DUPLICATE_ACROSS_PAGES");
        ids.add(item.id); rows.push(item);
      }
      if (value.nextCursor === null) {
        contract(JSON.stringify([...ids].sort()) === JSON.stringify([...expected].sort()), "SCOPED_RESOURCE_SET_MISMATCH");
        return rows;
      }
      contract(value.items.length > 0 && !cursors.has(value.nextCursor), "CURSOR_REPEATED_OR_EMPTY_PAGE");
      cursors.add(value.nextCursor); cursor = value.nextCursor;
    }
    throw new Error("PAGE_CAP_EXCEEDED");
  }
  async resourceBoundaries(resource: Resource, vector: Vector): Promise<Record<string, unknown>[]> {
    contract(vector.allowed.length >= 2 && vector.foreign.length >= 1 &&
      (vector.mode === "SET" ? vector.ungranted.length >= 1 : vector.mode === "ALL"),
      "MULTIPAGE_AND_NEGATIVE_FIXTURE_VECTORS_REQUIRED");
    const rows = await this.list(resource, vector.allowed, 1);
    await this.list(resource, vector.allowed, 200);
    for (const row of rows) {
      const detail = await this.detail(resource, String(row.id));
      contract(Object.entries(row).every(([key, value]) => JSON.stringify(detail[key]) === JSON.stringify(value)), "LIST_DETAIL_PROJECTION_MISMATCH");
    }
    for (const id of [...vector.foreign, ...vector.ungranted]) {
      await this.denied(`/api/v1/${resource}/${encodeURIComponent(id)}`, 404);
    }
    if (vector.foreign.length) {
      const url = new URL("/api/v1/" + resource, this.origin);
      url.searchParams.set("companyId", "synthetic-foreign-company");
      await this.denied(url.pathname + url.search, 422);
    }
    return rows;
  }
  async monitoring(id: string): Promise<MonitoringWire> {
    const response = await this.get(`/api/v1/objects/${encodeURIComponent(id)}/monitoring?days=90`);
    contract(response.status === 200, "AUTHORIZED_MONITORING_FAILED");
    const value = await response.json() as MonitoringWire;
    contract(value.pointId === id && value.provenance.catalogMode === "current", "MONITORING_BOUNDARY_OR_PROVENANCE_MISMATCH");
    return value;
  }
  async contractTypeMetadata(typeCode: string): Promise<ContractTypeWire> {
    const response = await this.get("/api/v1/contract-types?" + new URLSearchParams({ typeCode }));
    contract(response.status === 200, "AUTHORIZED_CONTRACT_TYPE_FAILED");
    contract(response.headers.get("cache-control")?.includes("no-store"), "NO_STORE_REQUIRED");
    const value = await response.json() as ContractTypeWire;
    contract(value.typeCode === typeCode, "CONTRACT_TYPE_SOURCE_CODE_MISMATCH");
    return value;
  }
  async contractObjects(contractId: string, cursor?: string, pageSize = 1): Promise<ContractObjectsWire> {
    const query = new URLSearchParams({ pageSize: String(pageSize) });
    if (cursor !== undefined) query.set("cursor", cursor);
    const response = await this.get(`/api/v1/contracts/${encodeURIComponent(contractId)}/objects?${query}`);
    contract(response.status === 200, "AUTHORIZED_CONTRACT_OBJECTS_FAILED");
    contract(response.headers.get("cache-control")?.includes("no-store"), "NO_STORE_REQUIRED");
    const value = await response.json() as ContractObjectsWire;
    contract(value.contractId === contractId && Array.isArray(value.items), "CONTRACT_OBJECT_LINK_SHAPE_MISMATCH");
    return value;
  }
  async contractDocuments(contractId: string, cursor?: string, pageSize = 1): Promise<ContractDocumentsWire> {
    const query = new URLSearchParams({ pageSize: String(pageSize) });
    if (cursor !== undefined) query.set("cursor", cursor);
    const response = await this.get(`/api/v1/contracts/${encodeURIComponent(contractId)}/documents?${query}`);
    contract(response.status === 200, "AUTHORIZED_CONTRACT_DOCUMENTS_FAILED");
    contract(response.headers.get("cache-control")?.includes("no-store"), "NO_STORE_REQUIRED");
    const value = await response.json() as ContractDocumentsWire;
    contract(value.contractId === contractId && Array.isArray(value.items), "CONTRACT_DOCUMENT_LINK_SHAPE_MISMATCH");
    return value;
  }
  async filteredContracts(typeCode: string, cursor?: string): Promise<FilteredContractsWire> {
    const query = new URLSearchParams({ pageSize: "1", typeCode });
    if (cursor !== undefined) query.set("cursor", cursor);
    const response = await this.get("/api/v1/contracts?" + query);
    contract(response.status === 200, "AUTHORIZED_FILTERED_CONTRACTS_FAILED");
    contract(response.headers.get("cache-control")?.includes("no-store"), "NO_STORE_REQUIRED");
    return await response.json() as FilteredContractsWire;
  }
  async document(id: string): Promise<DocumentWire> {
    const response = await this.get("/api/v1/documents/" + encodeURIComponent(id));
    contract(response.status === 200, "AUTHORIZED_DOCUMENT_FAILED");
    const value = await response.json() as DocumentWire;
    contract(value.id === id && Array.isArray(value.versions), "DOCUMENT_METADATA_MISMATCH");
    return value;
  }
  async content(docId: string, versionId: string, sha256: string): Promise<void> {
    const response = await this.get(`/api/v1/documents/${encodeURIComponent(docId)}/versions/${encodeURIComponent(versionId)}/content`);
    contract(response.status === 200 && response.headers.get("content-type")?.startsWith("application/octet-stream"), "BINARY_CONTENT_REQUIRED");
    const bytes = Buffer.from(await response.arrayBuffer());
    contract(createHash("sha256").update(bytes).digest("hex") === sha256, "EXACT_VERSION_BYTES_MISMATCH");
  }
}

export async function rentalScenario(app: ReadApplication, vectors: Vectors, relations: RentalRelations): Promise<void> {
  let contracts: Record<string, unknown>[] = [];
  for (const resource of ["objects", "counterparties", "contracts"] as const) {
    contract(vectors[resource], "RENTAL_FIXTURE_VECTOR_REQUIRED");
    const rows = await app.resourceBoundaries(resource, vectors[resource]);
    if (resource === "contracts") contracts = rows;
  }
  contract(contracts.every(row => row.counterpartyId === null || vectors.counterparties!.allowed.includes(String(row.counterpartyId))),
    "UNGRANTED_COUNTERPARTY_LINK_DISCLOSURE");
  await app.denied("/api/v1/documents", 403); // Machine identity is not a docs user.
  contract(relations.contracts.length === contracts.length && relations.contracts.every(({ expected }) => {
    const row = contracts.find(value => value.id === expected.id);
    return row && Object.entries(expected).every(([key, value]) => JSON.stringify(row[key]) === JSON.stringify(value));
  }), "RAW_CONTRACT_LIST_EXPECTATION_MISMATCH");
  await rentalRelationsScenario(app, relations);
}

export async function operationsScenario(app: ReadApplication, vectors: Vectors): Promise<void> {
  for (const resource of ["objects", "equipment"] as const) {
    contract(vectors[resource], "OPERATIONS_FIXTURE_VECTOR_REQUIRED");
    const rows = await app.resourceBoundaries(resource, vectors[resource]);
    if (resource === "equipment") contract(rows.every(row => row.level === "station" &&
      (row.objectId === null || vectors.objects!.allowed.includes(String(row.objectId)))), "UNGRANTED_OBJECT_LINK_DISCLOSURE");
  }
  for (const id of vectors.objects!.allowed) await app.monitoring(id);
  for (const id of [...vectors.objects!.foreign, ...vectors.objects!.ungranted]) {
    await app.denied(`/api/v1/objects/${encodeURIComponent(id)}/monitoring?days=90`, 404);
  }
  await app.denied("/api/v1/documents", 403);
}

/** No implicit permission: this checks the assigned profile, never issues scopes/grants. */
export function requireDocumentRelationAuthority(authority: RelationAuthority): void {
  const usable = (resource: "contracts" | "documents") => {
    const grant = authority.resourceScopes?.[resource];
    return grant?.mode === "ALL" || (grant?.mode === "SET" && Array.isArray(grant.ids) && grant.ids.length > 0);
  };
  contract(authority.scopes.includes("contracts:read") && authority.scopes.includes("documents:read") &&
    usable("contracts") && usable("documents"), "DOCUMENT_RELATIONS_BLOCKED_BY_PROFILE");
}

/** Exact effective IDs, supplied by the synthetic manifest, not native inventories. */
export async function relationPages<Page extends ContractObjectsWire | ContractDocumentsWire>(
  read: (cursor?: string) => Promise<Page>, vector: RelationVector,
  idsOf: (page: Page) => string[], validate: (page: Page) => void = () => {},
): Promise<string | null> {
  contract(new Set(vector.allowed).size === vector.allowed.length &&
    vector.hidden.every(id => !vector.allowed.includes(id)), "INVALID_RELATION_EXPECTATION");
  const ids = new Set<string>(), cursors = new Set<string>();
  let cursor: string | undefined, first: string | null = null;
  for (let count = 0; count < 100; count++) {
    const page = await read(cursor);
    contract(page.contractId === vector.contractId && Array.isArray(page.items), "RELATION_PARENT_MISMATCH");
    contract(page.total === vector.allowed.length && page.items.length <= 1 &&
      (page.nextCursor === null || (typeof page.nextCursor === "string" && page.nextCursor.length > 0)),
      "RELATION_PAGE_SHAPE_OR_VISIBLE_TOTAL_MISMATCH");
    validate(page);
    const batch = idsOf(page);
    contract(batch.length === page.items.length, "RELATION_ITEM_PROJECTION_MISMATCH");
    for (const id of batch) {
      contract(typeof id === "string" && vector.allowed.includes(id) && !vector.hidden.includes(id),
        "INDEPENDENTLY_HIDDEN_RELATION_DISCLOSED");
      contract(!ids.has(id), "DUPLICATE_RELATION_ACROSS_PAGES");
      ids.add(id);
    }
    if (page.nextCursor === null) {
      contract(ids.size === vector.allowed.length && vector.allowed.every(id => ids.has(id)), "RELATION_SET_MISMATCH");
      return first;
    }
    contract(batch.length > 0 && !cursors.has(page.nextCursor), "RELATION_CURSOR_REPEATED_OR_EMPTY_PAGE");
    if (first === null) first = page.nextCursor;
    cursors.add(page.nextCursor); cursor = page.nextCursor;
  }
  throw new Error("RELATION_PAGE_CAP_EXCEEDED");
}

function relationPath(contractId: string, resource: "objects" | "documents", query: Record<string, string> = {}): string {
  return `/api/v1/contracts/${encodeURIComponent(contractId)}/${resource}?` + new URLSearchParams({ pageSize: "1", ...query });
}

async function cursorBoundaries(app: ReadApplication, resource: "objects" | "documents", vector: RelationVector,
  others: RelationVector[], cursor: string | null): Promise<void> {
  // Relation routes accept only pageSize/cursor, never list filters.
  await app.denied(relationPath(vector.contractId, resource, { q: "synthetic" }), 422);
  if (cursor === null) return;
  await app.denied(relationPath(vector.contractId, resource, { cursor, pageSize: "2" }), 400);
  const other = others.find(value => value.contractId !== vector.contractId);
  contract(other, "SECOND_VISIBLE_RELATION_PARENT_REQUIRED");
  await app.denied(relationPath(other.contractId, resource, { cursor }), 400);
}

export async function rentalRelationsScenario(app: ReadApplication, relations: RentalRelations): Promise<void> {
  contract(relations.contracts.length >= 2 && relations.hiddenParents.length > 0 && relations.foreignParents.length > 0 &&
    relations.contracts.some(value => value.objects.allowed.length >= 2 && value.objects.hidden.length > 0),
    "RENTAL_RELATION_FIXTURE_REQUIRED");
  for (const { expected, metadata, objects } of relations.contracts) {
    contract(objects.contractId === expected.id && objects.scopeType === expected.scopeType, "RELATION_EXPECTED_PARENT_MISMATCH");
    const actual = await app.detail("contracts", expected.id);
    contract(Object.entries(expected).every(([key, value]) => JSON.stringify(actual[key]) === JSON.stringify(value)),
      "RAW_CONTRACT_DETAIL_EXPECTATION_MISMATCH");
    // Keep raw typeCode, whitespace/case and raw validUntil; no enum/date conversion.
    if (expected.typeCode !== null && expected.typeCode.length > 0) {
      contract(metadata && metadata.typeCode === expected.typeCode, "EXACT_RAW_TYPE_METADATA_EXPECTATION_REQUIRED");
      const value = await app.contractTypeMetadata(expected.typeCode);
      contract(Object.entries(metadata).every(([key, field]) => value[key as keyof ContractTypeWire] === field),
        "RAW_TYPE_METADATA_MISMATCH");
      const matching = relations.contracts.filter(row => row.expected.typeCode === expected.typeCode).map(row => row.expected.id);
      const ids = new Set<string>(), cursors = new Set<string>();
      let cursor: string | undefined, complete = false;
      for (let count = 0; count < 100; count++) {
        const page = await app.filteredContracts(expected.typeCode, cursor);
        contract(Array.isArray(page.items) && page.total === matching.length && page.items.length <= 1 &&
          (page.nextCursor === null || (typeof page.nextCursor === "string" && page.nextCursor.length > 0)), "FILTERED_CONTRACT_PAGE_MISMATCH");
        for (const row of page.items) {
          contract(row.typeCode === expected.typeCode && matching.includes(row.id) && !ids.has(row.id), "EXACT_TYPE_FILTER_OR_DUPLICATE_MISMATCH");
          ids.add(row.id);
        }
        if (page.nextCursor === null) {
          contract(ids.size === matching.length, "FILTERED_CONTRACT_SET_MISMATCH"); complete = true; break;
        }
        contract(page.items.length > 0 && !cursors.has(page.nextCursor), "FILTERED_CONTRACT_CURSOR_REPEATED");
        cursors.add(page.nextCursor); cursor = page.nextCursor;
      }
      contract(complete, "FILTERED_CONTRACT_PAGE_CAP_EXCEEDED");
    } else contract(metadata === null, "EMPTY_RAW_TYPE_MUST_NOT_QUERY_METADATA");
    const first = await relationPages(cursor => app.contractObjects(expected.id, cursor), objects,
      page => page.items.map(item => item.objectId), page => {
        contract(page.scopeType === objects.scopeType, "EXACT_NATIVE_SCOPE_TYPE_REQUIRED");
        if (page.scopeType !== "locations") contract(page.items.length === 0 && page.total === 0, "NO_COMPANY_SCOPE_EXPANSION");
      });
    await cursorBoundaries(app, "objects", objects, relations.contracts.map(value => value.objects), first);
    await app.denied(relationPath(expected.id, "documents"), 403); // service is denied before parent visibility.
  }
  for (const id of [...relations.hiddenParents, ...relations.foreignParents]) {
    await app.denied(relationPath(id, "objects"), 404);
    await app.denied(relationPath(id, "documents"), 403);
  }
  const cursor = await app.firstCursor("contracts");
  await app.denied("/api/v1/contracts?" + new URLSearchParams({ pageSize: "1", cursor, typeCode: "different synthetic type" }), 400);
  await app.denied("/api/v1/contracts?" + new URLSearchParams({ pageSize: "1", cursor, q: "changed synthetic filter" }), 400);
}

/** Positive traversal requires separately approved delegated scopes and grants. */
export async function documentRelationsScenario(app: ReadApplication, relations: DocumentRelations): Promise<void> {
  contract(relations.contracts.length >= 2 && relations.hiddenParents.length > 0 && relations.foreignParents.length > 0 &&
    relations.contracts.some(value => value.allowed.length >= 2 && value.hidden.length > 0), "DOCUMENT_RELATION_FIXTURE_REQUIRED");
  for (const vector of relations.contracts) {
    const first = await relationPages(cursor => app.contractDocuments(vector.contractId, cursor), vector,
      page => page.items.map(item => item.documentId));
    await cursorBoundaries(app, "documents", vector, relations.contracts, first);
    // IDs are metadata only. Existing exact-version content/denials remain in run.ts.
  }
  for (const id of [...relations.hiddenParents, ...relations.foreignParents]) {
    await app.denied(relationPath(id, "documents"), 404);
  }
}
