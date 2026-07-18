/**
 * CRUD для конфигов коннекторов.
 * Dual-mode: localStorage (demo) / API (production).
 *
 * Генератор демо-синхронизации удалён: он создавал фиктивные документы
 * («Счёт-фактура №1234», случайные суммы) и писал их в РЕАЛЬНОЕ хранилище
 * записей, откуда их уже не отличить от загруженных. Реальный polling —
 * задача Слоя 2 (Python + cron).
 */

import type { Connector } from '@/types'
import { isApiEnabled, get, post, patch, del } from './apiClient'
import { apiToConnector, connectorToApi, type ApiConnector } from './apiMappers'
import { getItem, setItem } from './storage'

function connectorsKey(companyId: string): string {
  return `clearledger-connectors-${companyId}`
}

let counter = getItem<number>('clearledger-connector-counter', 0)

function nextConnectorId(): string {
  counter++
  setItem('clearledger-connector-counter', counter)
  return `conn-${counter}`
}

export async function getConnectors(companyId: string): Promise<Connector[]> {
  if (isApiEnabled()) {
    const list = await get<ApiConnector[]>('/api/connectors', { company_id: companyId })
    return list.map(apiToConnector)
  }
  return getItem<Connector[]>(connectorsKey(companyId), [])
}

export async function getConnector(companyId: string, id: string): Promise<Connector | undefined> {
  if (isApiEnabled()) {
    try {
      const a = await get<ApiConnector>(`/api/connectors/${id}`)
      return apiToConnector(a)
    } catch {
      return undefined
    }
  }
  return getItem<Connector[]>(connectorsKey(companyId), []).find((c) => c.id === id)
}

export interface CreateConnectorInput {
  name: string
  type: string
  url: string
  status?: Connector['status']
  categoryId: string
  interval: number
  companyId: string
}

export async function createConnector(input: CreateConnectorInput): Promise<Connector> {
  if (isApiEnabled()) {
    const body = connectorToApi({
      name: input.name,
      type: input.type,
      url: input.url,
      status: input.status ?? 'disabled',
      categoryId: input.categoryId,
      interval: input.interval,
      companyId: input.companyId,
    })
    const a = await post<ApiConnector>('/api/connectors', body)
    return apiToConnector(a)
  }

  const connector: Connector = {
    id: nextConnectorId(),
    name: input.name,
    type: input.type,
    url: input.url,
    status: input.status ?? 'disabled',
    recordsCount: 0,
    errorsCount: 0,
    categoryId: input.categoryId,
    interval: input.interval,
    companyId: input.companyId,
  }
  const list = getItem<Connector[]>(connectorsKey(input.companyId), [])
  list.push(connector)
  setItem(connectorsKey(input.companyId), list)
  return connector
}

export async function updateConnector(
  companyId: string,
  id: string,
  updates: Partial<Omit<Connector, 'id' | 'companyId'>>,
): Promise<Connector | undefined> {
  if (isApiEnabled()) {
    const body = connectorToApi(updates)
    const a = await patch<ApiConnector>(`/api/connectors/${id}`, body)
    return apiToConnector(a)
  }

  const list = getItem<Connector[]>(connectorsKey(companyId), [])
  const idx = list.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates }
  setItem(connectorsKey(companyId), list)
  return list[idx]
}

export async function deleteConnector(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try {
      await del(`/api/connectors/${id}`)
      return true
    } catch {
      return false
    }
  }

  const list = getItem<Connector[]>(connectorsKey(companyId), [])
  const filtered = list.filter((c) => c.id !== id)
  if (filtered.length === list.length) return false
  setItem(connectorsKey(companyId), filtered)
  return true
}
