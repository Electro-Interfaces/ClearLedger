/** External server consumer compile fixture. It does not add a transport to Core. */
import type { components, operations, paths } from "../../src/generated/partner-api";

export type ObjectWire = components["schemas"]["Object"];
export type ObjectPage = operations["listObjects"]["responses"][200]["content"]["application/json"];
export type ObjectsQuery = NonNullable<operations["listObjects"]["parameters"]["query"]>;
export type Problem = operations["getObject"]["responses"][404]["content"]["application/problem+json"];
export type DownloadWire = operations["downloadDocumentVersion"]["responses"][200]["content"]["application/octet-stream"];

export const query: ObjectsQuery = { pageSize: 50, dateFrom: "2026-01-02", q: "Example" };
export const point: ObjectWire = { id: "synthetic.point-1", code: "P-1", name: "Synthetic point",
  type: "ezs", status: "active", address: null, latitude: null, longitude: null };
export const label = (row: ObjectWire): string => row.name + (row.address === null ? "" : ": " + row.address);

// Nullable is not optional: address must be present even when it is null.
// @ts-expect-error missing required nullable fields
const missingNullableFields: ObjectWire = { id: "p", code: "p", name: "p", type: "ezs", status: "active" };
// @ts-expect-error pageSize is numeric on the typed query contract
const wrongQuery: ObjectsQuery = { pageSize: "50" };
// @ts-expect-error query does not accept a tenant override
const tenantOverride: ObjectsQuery = { companyId: "foreign" };
// @ts-expect-error this API declares no POST /objects write operation
const inventedWrite: paths["/objects"]["post"] = {};
// @ts-expect-error binary download 200 is not application/json
type InventedDownloadJSON = operations["downloadDocumentVersion"]["responses"][200]["content"]["application/json"];
