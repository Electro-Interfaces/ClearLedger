/** External compile fixture: source values and scoped classifier metadata. */
import type { components, operations, paths } from "../../src/generated/partner-api";
type Contract = components["schemas"]["Contract"];
type Query = NonNullable<operations["listContracts"]["parameters"]["query"]>;
type MetadataQuery = operations["getContractTypeMetadata"]["parameters"]["query"];
type Metadata = operations["getContractTypeMetadata"]["responses"][200]["content"]["application/json"];
export const opaqueQuery: Query = { typeCode: " Custom Ё /Energy:01 ", pageSize: 50 };
export const metadataQuery: MetadataQuery = { typeCode: " Custom Ё /Energy:01 " };
export const contract: Contract = { id: "c", number: "1", date: null, title: null, isClosed: false,
  scopeType: "company", counterpartyId: null, typeCode: null, validUntil: "31.12.2030" };
export const unknownMetadata: Metadata = { typeCode: "unknown", label: null, gkBasis: null,
  direction: null, isActive: null };
export const inactive: Metadata = { typeCode: "old", label: "Old", gkBasis: null,
  direction: "any", isActive: false };
// @ts-expect-error source nullable fields are required on the wire
const missingNullable: Contract = { id: "c", number: "1", date: null, title: null, isClosed: false, scopeType: "company", counterpartyId: null };
// @ts-expect-error classifier code is required for scoped metadata
const missingCode: MetadataQuery = {};
// @ts-expect-error no caller tenant override
const tenantOverride: MetadataQuery = { typeCode: "rent", companyId: "foreign" };
// @ts-expect-error metadata is not a catalog search endpoint
const inventedSearch: MetadataQuery = { typeCode: "rent", q: "anything" };
// @ts-expect-error no classifier cursor or enumeration
const inventedCursor: MetadataQuery = { typeCode: "rent", cursor: "c" };
// @ts-expect-error source validity is a nullable string, not a numeric timestamp
const numericExpiry: Contract = { ...contract, validUntil: 0 };
// @ts-expect-error active status is boolean or null
const badStatus: Metadata = { ...unknownMetadata, isActive: "false" };
// @ts-expect-error the API declares no classifier write
const inventedWrite: paths["/contract-types"]["post"] = {};
// @ts-expect-error metadata GET has no body
const inventedBody: operations["getContractTypeMetadata"]["requestBody"] = {};
// @ts-expect-error typeCode only filters contracts
const otherResource: NonNullable<operations["listObjects"]["parameters"]["query"]> = { typeCode: "rent" };
