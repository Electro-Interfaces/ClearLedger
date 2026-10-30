/** Compile-only external consumer: an explicit link is not file authority. */
import type { operations, paths } from "../../src/generated/partner-api";
type Relation = operations["listContractDocuments"];
export type ContractDocumentsPage = Relation["responses"][200]["content"]["application/json"];
export type ContractDocumentsQuery = NonNullable<Relation["parameters"]["query"]>;
export const query: ContractDocumentsQuery = { pageSize: 50, cursor: null };
export const path: Relation["parameters"]["path"] = { contractId: "synthetic-contract" };
export const page: ContractDocumentsPage = { contractId: "synthetic-contract", items: [{ documentId: "synthetic-document" }], total: 1, nextCursor: null };
export const documentIds = (value: ContractDocumentsPage): string[] => value.items.map(item => item.documentId);
// @ts-expect-error the caller cannot override the tenant
const tenantOverride: ContractDocumentsQuery = { companyId: "foreign" };
// @ts-expect-error the relationship defines no POST/write operation
const inventedWrite: paths["/contracts/{contractId}/documents"]["post"] = {};
// @ts-expect-error the path requires contractId
const missingContract: Relation["parameters"]["path"] = {};
// @ts-expect-error nextCursor must be present on the last page too
const missingCursor: ContractDocumentsPage = { contractId: "c", items: [], total: 0 };
// @ts-expect-error GET has no request body
const inventedBody: Relation["requestBody"] = {};
// @ts-expect-error document associations contain no file bytes
const inventedBytes: ContractDocumentsPage["items"][number] = { documentId: "d", content: "bytes" };
