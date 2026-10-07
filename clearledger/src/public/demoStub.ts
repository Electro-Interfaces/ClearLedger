/**
 * Заглушка демо-данных для публичной сборки (vite.public.config.ts подставляет её вместо
 * `@/demo/demoApi`). Демо-данные перечисляют почти все адреса API с образцами ответов —
 * это карта API, и посетителю без входа её отдавать незачем. Демо-режима в публичной
 * сборке нет: страницы входа и ссылок всегда ходят в настоящий API.
 */
export class DemoReadOnlyError extends Error {}

const off = (): never => { throw new Error('Демо-режим в публичной сборке не поддерживается') }

export async function demoGet<T>(): Promise<T> { return off() }
export async function demoPost<T>(): Promise<T> { return off() }
export async function demoWrite<T>(): Promise<T> { return off() }
