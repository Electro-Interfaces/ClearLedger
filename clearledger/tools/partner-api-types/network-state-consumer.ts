/** Вымышленный wire example; без fetch, transport, токенов и исполнения запросов. */
import type { operations, paths } from "../../src/generated/partner-api";

export type NetworkQuery = NonNullable<operations["getNetworkState"]["parameters"]["query"]>;
export type NetworkState = operations["getNetworkState"]["responses"][200]["content"]["application/json"];
export type NetworkItem = NetworkState["items"][number];
export type StatusCounts = NetworkState["summary"]["byStatus"];
export type NetworkGet = paths["/monitoring/network-state"]["get"];
export type NetworkProblem = operations["getNetworkState"]["responses"][400]["content"]["application/problem+json"];

export const firstPage: NetworkQuery = {
  pageSize: 50, asOf: "2026-10-30", region: "Учебный регион", onlyProblems: true,
};
export const statusCounts: StatusCounts = {
  working: 1, no_link: 0, disabled: 0, decommissioned: 0,
  on_repair: 0, maintenance: 0, not_working: 0, unknown: 0,
};
export const response: NetworkState = {
  items: [{ objectId: "Учебная точка 1", status: "working",
    lastChargeAt: null, silentDays: null, mismatch: true }],
  summary: { stations: 1, mismatch: 1, byStatus: statusCounts },
  context: { asOf: "2026-10-30T23:59:59.999999+03:00", dataThrough: null,
    dataLagHours: null, requestedDate: "2026-10-30", catalogMode: "current",
    boundaryScope: "authorizedOperatedRegion", availability: "unknown" },
  nextCursor: null,
};

// Точная строка operation/accessBoundary принадлежит вызывающему коду, не API query.
// При смене user/company/client/install/grant/scopes/resource policy начинайте заново.
export type Traversal = Readonly<{
  operation: "getNetworkState";
  accessBoundary: string;
  query: Readonly<NetworkQuery>;
}>;
export const traversal: Traversal = {
  operation: "getNetworkState", accessBoundary: "fictional-user-company-grant-v1", query: firstPage,
};
export function continuation(previous: Traversal, page: NetworkState,
  currentOperation: string, currentAccessBoundary: string): Traversal | null {
  if (currentOperation !== previous.operation || currentAccessBoundary !== previous.accessBoundary) {
    throw new Error("Restart after operation/access change");
  }
  // summary относится ко всему M до страницы; nextCursor=null завершает обход.
  if (page.nextCursor === null) return null;
  return { ...previous, query: { ...previous.query, cursor: page.nextCursor } };
}
export function restart(previous: Traversal): Traversal {
  const { cursor: omittedCursor, ...filtersAndPageSize } = previous.query;
  return { ...previous, query: filtersAndPageSize };
}
// Решения для вызывающего кода, автоматические повторы здесь не выполняются.
export function refusal(status: 400 | 401 | 403 | 503): string {
  switch (status) {
    case 400: return "Discard partial traversal; restart without cursor with identical filters/pageSize";
    case 401: return "Stop; obtain current authorized credentials before a new traversal";
    case 403: return "Stop; owner must resolve access; do not broaden selection";
    case 503: return "No partial success; bounded retry policy belongs to caller, no SLA promise";
  }
}

// @ts-expect-error pageSize передаётся числом
const textualSize: NetworkQuery = { pageSize: "50" };
// @ts-expect-error onlyProblems в wire query type — boolean
const textualBoolean: NetworkQuery = { onlyProblems: "true" };
// @ts-expect-error asOf — ISO date string, не Date object
const dateObject: NetworkQuery = { asOf: new Date() };
// @ts-expect-error финансового отбора нет
const financialQuery: NetworkQuery = { minRevenue: 1 };
// @ts-expect-error tenant нельзя выбирать параметром
const tenantOverride: NetworkQuery = { companyId: "foreign" };
// @ts-expect-error financial field не входит в пять полей элемента
const financialItem: NetworkItem = { ...response.items[0]!, revenue: 1 };
// @ts-expect-error status — закрытый enum
const inventedStatus: NetworkItem = { ...response.items[0]!, status: "active" };
// @ts-expect-error status map сохраняет underscore wire key
const camelStatus: StatusCounts = { ...statusCounts, noLink: 0 };
const { no_link: omittedStatus, ...withoutNoLink } = statusCounts;
// @ts-expect-error все восемь status keys обязательны
const missingStatus: StatusCounts = withoutNoLink;
const { lastChargeAt: omittedNullable, ...withoutLastCharge } = response.items[0]!;
// @ts-expect-error nullable lastChargeAt обязателен
const missingNullable: NetworkItem = withoutLastCharge;
// @ts-expect-error GET не принимает body
const requestBody: operations["getNetworkState"]["requestBody"] = {};
// @ts-expect-error POST состояния сети не объявлен
const unsupportedPost: paths["/monitoring/network-state"]["post"] = {};
