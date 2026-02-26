/**
 * CRUD для конфигов коннекторов в localStorage.
 * Реальный polling — задача Слоя 2 (Python + cron).
 * Слой 1 хранит только конфигурации.
 */

import type { Connector } from '@/types'
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

export function getConnectors(companyId: string): Connector[] {
  return getItem<Connector[]>(connectorsKey(companyId), [])
}

export function getConnector(companyId: string, id: string): Connector | undefined {
  return getConnectors(companyId).find((c) => c.id === id)
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

export function createConnector(input: CreateConnectorInput): Connector {
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
  const list = getConnectors(input.companyId)
  list.push(connector)
  setItem(connectorsKey(input.companyId), list)
  return connector
}

export function updateConnector(
  companyId: string,
  id: string,
  updates: Partial<Omit<Connector, 'id' | 'companyId'>>,
): Connector | undefined {
  const list = getConnectors(companyId)
  const idx = list.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates }
  setItem(connectorsKey(companyId), list)
  return list[idx]
}

export function deleteConnector(companyId: string, id: string): boolean {
  const list = getConnectors(companyId)
  const filtered = list.filter((c) => c.id !== id)
  if (filtered.length === list.length) return false
  setItem(connectorsKey(companyId), filtered)
  return true
}
