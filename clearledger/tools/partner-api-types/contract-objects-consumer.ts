/** Compile-only external consumer of explicit, access-filtered contract links. */
import type { operations, paths } from "../../src/generated/partner-api";

type ListContractObjects = operations["listContractObjects"];
export type ContractObjectsPage = ListContractObjects["responses"][200]["content"]["application/json"];
export type ContractObjectsQuery = NonNullable<ListContractObjects["parameters"]["query"]>;
export const query: ContractObjectsQuery = { pageSize: 50, cursor: null };
export const path: ListContractObjects["parameters"]["path"] = { contractId: "synthetic-contract" };
export const page: ContractObjectsPage = { contractId: "synthetic-contract", scopeType: "locations",
  items: [{ objectId: "ЭЗС Север 1" }], total: 1, nextCursor: null };
export const objectIds = (value: ContractObjectsPage): string[] => value.items.map(item => item.objectId);

// @ts-expect-error tenant access cannot be overridden by the consumer
const tenantOverride: ContractObjectsQuery = { companyId: "foreign" };
// @ts-expect-error this relationship declares no write operation
const inventedWrite: paths["/contracts/{contractId}/objects"]["post"] = {};
// @ts-expect-error the contract identifier is a required path parameter
const missingContract: ListContractObjects["parameters"]["path"] = {};
// @ts-expect-error nextCursor is required even for the last page
const missingCursor: ContractObjectsPage = { contractId: "c", scopeType: "locations", items: [], total: 0 };
// @ts-expect-error GET has no request body
const inventedBody: ListContractObjects["requestBody"] = {};
