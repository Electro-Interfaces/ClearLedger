/** Compile-only partner server example; HTTP authorization and validation remain server-side. */
import type { components, operations, paths } from "../../src/generated/partner-api";

export type CreateBody = operations["createContract"]["requestBody"]["content"]["application/json"];
export type Created = operations["createContract"]["responses"][201]["content"]["application/json"];
export type Replayed = operations["createContract"]["responses"][200]["content"]["application/json"];
export type CreateProblem = operations["createContract"]["responses"][403]["content"]["application/problem+json"];

// UUID/date syntax, byte limits, array bounds and current permissions require server validation.
export const body: CreateBody = {
  kind: "contract-card", creationKey: "00000000-0000-4000-8000-000000000001",
  number: "SYN-1", date: "2026-11-01", type: "Synthetic contract", typeCode: " Custom Ё /Energy:01 ",
  organizationId: "00000000-0000-4000-8000-000000000002",
  counterpartyId: "00000000-0000-4000-8000-000000000003",
  coverage: { kind: "locations", locationIds: [" synthetic.location-1 "] }, validUntil: null,
};
export const commented: components["schemas"]["ContractCreateBody"] = { ...body, comment: null };
export const created: Created = { contractId: "00000000-0000-4000-8000-000000000004", replayed: false };
export const replayed: Replayed = { ...created, replayed: true };
export type CollectionPost = paths["/contracts"]["post"];

const { validUntil: omittedUntil, ...withoutUntil } = body;
// @ts-expect-error nullable validUntil is required on the wire
const missingUntil: CreateBody = withoutUntil;
const { creationKey: omittedKey, ...withoutKey } = body;
// @ts-expect-error creationKey is required for replay identity
const missingKey: CreateBody = withoutKey;
// @ts-expect-error only contract-card is declared
const wrongKind: CreateBody = { ...body, kind: "invoice" };
// @ts-expect-error coverage has an exact discriminator
const wrongCoverage: CreateBody = { ...body, coverage: { kind: "all", locationIds: [] } };
// @ts-expect-error locationIds is an array, not one identifier
const scalarLocation: CreateBody = { ...body, coverage: { kind: "locations", locationIds: "one" } };
// @ts-expect-error callers cannot override the tenant
const tenantOverride: CreateBody = { ...body, companyId: "foreign" };
// @ts-expect-error dates are wire strings, not Date instances
const dateObject: CreateBody = { ...body, date: new Date("2026-11-01") };
// @ts-expect-error nullable comment is textual
const numericComment: CreateBody = { ...body, comment: 1 };
// @ts-expect-error replayed is boolean
const numericReplay: Replayed = { ...replayed, replayed: 1 };
// @ts-expect-error create result exposes contractId, not a readable contract representation
const leakedResult: Created = { ...created, number: "SYN-1" };
