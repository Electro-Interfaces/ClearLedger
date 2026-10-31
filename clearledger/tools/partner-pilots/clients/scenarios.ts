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
    const value = await response.json() as ContractTypeWire;
    contract(value.typeCode === typeCode, "CONTRACT_TYPE_SOURCE_CODE_MISMATCH");
    return value;
  }
  async contractObjects(contractId: string, cursor?: string): Promise<ContractObjectsWire> {
    const query = new URLSearchParams({ pageSize: "1" });
    if (cursor !== undefined) query.set("cursor", cursor);
    const response = await this.get(`/api/v1/contracts/${encodeURIComponent(contractId)}/objects?${query}`);
    contract(response.status === 200, "AUTHORIZED_CONTRACT_OBJECTS_FAILED");
    const value = await response.json() as ContractObjectsWire;
    contract(value.contractId === contractId && Array.isArray(value.items), "CONTRACT_OBJECT_LINK_SHAPE_MISMATCH");
    return value;
  }
  async contractDocuments(contractId: string, cursor?: string): Promise<ContractDocumentsWire> {
    const query = new URLSearchParams({ pageSize: "1" });
    if (cursor !== undefined) query.set("cursor", cursor);
    const response = await this.get(`/api/v1/contracts/${encodeURIComponent(contractId)}/documents?${query}`);
    contract(response.status === 200, "AUTHORIZED_CONTRACT_DOCUMENTS_FAILED");
    const value = await response.json() as ContractDocumentsWire;
    contract(value.contractId === contractId && Array.isArray(value.items), "CONTRACT_DOCUMENT_LINK_SHAPE_MISMATCH");
    return value;
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

export async function rentalScenario(app: ReadApplication, vectors: Vectors): Promise<void> {
  let contracts: Record<string, unknown>[] = [];
  for (const resource of ["objects", "counterparties", "contracts"] as const) {
    contract(vectors[resource], "RENTAL_FIXTURE_VECTOR_REQUIRED");
    const rows = await app.resourceBoundaries(resource, vectors[resource]);
    if (resource === "contracts") contracts = rows;
  }
  contract(contracts.every(row => row.counterpartyId === null || vectors.counterparties!.allowed.includes(String(row.counterpartyId))),
    "UNGRANTED_COUNTERPARTY_LINK_DISCLOSURE");
  await app.denied("/api/v1/documents", 403); // Machine identity is not a docs user.
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
