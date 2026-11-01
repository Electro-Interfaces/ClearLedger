/** Только компиляция примера: авторизацию, ограничения строк и курсора проверяет сервер. */
import type { operations, paths } from "../../src/generated/partner-api";

export type ChoicesQuery = operations["getContractCreateOptions"]["parameters"]["query"];
export type Choices = operations["getContractCreateOptions"]["responses"][200]["content"]["application/json"];
export type ChoicesProblem = operations["getContractCreateOptions"]["responses"][429]["content"]["application/problem+json"];
export type ChoicesHeaders = operations["getContractCreateOptions"]["responses"][429]["headers"];

export const firstPage: ChoicesQuery = { resource: "type", pageSize: 50 };
export const nextPage: ChoicesQuery = { ...firstPage, cursor: "synthetic-opaque-cursor" };
export const response: Choices = {
  resource: "type", items: [{ value: "  Synthetic type  " }],
  selectionVersion: "synthetic-opaque-version", nextCursor: null,
};
export const quotaHeaders: ChoicesHeaders = {
  "Retry-After": "5", "Cache-Control": "no-store", "X-Request-Id": "synthetic-request-id",
};
export type ChoicesGet = paths["/contracts/create-options"]["get"];

// @ts-expect-error resource обязателен
const missingResource: ChoicesQuery = { pageSize: 50 };
// @ts-expect-error только четыре объявленных домена
const unknownResource: ChoicesQuery = { resource: "contracts" };
// @ts-expect-error размер страницы передаётся числом
const textualSize: ChoicesQuery = { resource: "location", pageSize: "50" };
// @ts-expect-error tenant не выбирается параметром запроса
const tenantOverride: ChoicesQuery = { resource: "type", companyId: "foreign" };
const { nextCursor: omittedCursor, ...withoutCursor } = response;
// @ts-expect-error nextCursor nullable, но обязателен в ответе
const missingCursor: Choices = withoutCursor;
// @ts-expect-error курсор строковый или null
const numericCursor: Choices = { ...response, nextCursor: 1 };
// @ts-expect-error значения справочника передаются строками
const numericValue: Choices = { ...response, items: [{ value: 1 }] };
// @ts-expect-error внутренний идентификатор не входит в публичный элемент
const internalId: Choices = { ...response, items: [{ value: "type", id: "private" }] };
// @ts-expect-error GET не принимает тело
const requestBody: operations["getContractCreateOptions"]["requestBody"] = {};
// @ts-expect-error операция выбора не объявляет POST
const unsupportedPost: paths["/contracts/create-options"]["post"] = {};
