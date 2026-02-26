/**
 * CRUD для конфигов коннекторов в localStorage.
 * Demo-sync: simulateSync генерирует тестовые записи через intake.
 * Реальный polling — задача Слоя 2 (Python + cron).
 */

import type { Connector, DataEntry } from '@/types'
import { getItem, setItem, nextId, entriesKey } from './storage'
import { logEvent } from './auditService'

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

// ---- Demo Sync ----

const EMAIL_SUBJECTS = [
  'Акт сверки за январь 2025',
  'Счёт-фактура №1234 от 15.01.2025',
  'Накладная на поставку ГСМ',
  'Договор поставки №45-2025',
  'Счёт на оплату №789',
]

const ONEС_DOCS = [
  'Реализация товаров и услуг 00-000123',
  'Поступление на расчётный счёт 00-000456',
  'Платёжное поручение исходящее №789',
  'Корректировка долга',
  'Акт об оказании услуг №321',
]

const API_DOCS = [
  'Транзакция #TX-2025-001',
  'Отгрузка #SHP-45678',
  'Заявка на поставку #REQ-99',
  'Инвентаризация #INV-2025-02',
  'Приходный ордер #REC-112',
]

function randomItems<T>(arr: T[], count: number): T[] {
  const shuffled = [...arr].sort(() => Math.random() - 0.5)
  return shuffled.slice(0, count)
}

/** Симуляция синхронизации: генерирует 2-5 DataEntry */
export function simulateSync(companyId: string, connectorId: string): { entries: DataEntry[]; error?: string } {
  const connector = getConnector(companyId, connectorId)
  if (!connector) return { entries: [], error: 'Коннектор не найден' }
  if (connector.status === 'disabled') return { entries: [], error: 'Коннектор отключён' }

  const count = 2 + Math.floor(Math.random() * 4) // 2-5
  const now = new Date().toISOString()
  const newEntries: DataEntry[] = []

  // Выбираем шаблоны в зависимости от типа коннектора
  let templates: string[]
  let source: DataEntry['source']
  if (connector.type === 'email') {
    templates = randomItems(EMAIL_SUBJECTS, count)
    source = 'email'
  } else if (connector.type === '1c') {
    templates = randomItems(ONEС_DOCS, count)
    source = 'oneC'
  } else {
    templates = randomItems(API_DOCS, count)
    source = 'api'
  }

  for (let i = 0; i < count; i++) {
    const entry: DataEntry = {
      id: nextId(),
      title: templates[i] ?? `Запись ${i + 1} от ${connector.name}`,
      categoryId: connector.categoryId || 'documents',
      subcategoryId: 'incoming',
      companyId,
      status: 'new',
      source,
      sourceLabel: `Коннектор: ${connector.name}`,
      metadata: {
        _syncedFrom: connectorId,
        _syncedAt: now,
      },
      createdAt: now,
      updatedAt: now,
    }
    newEntries.push(entry)
  }

  // Сохраняем записи
  const existing = getItem<DataEntry[]>(entriesKey(companyId), [])
  setItem(entriesKey(companyId), [...existing, ...newEntries])

  // Обновляем коннектор
  updateConnector(companyId, connectorId, {
    lastSync: now,
    lastSyncAt: now,
    syncStatus: 'synced',
    recordsCount: connector.recordsCount + count,
  })

  // Аудит
  logEvent({
    companyId,
    action: 'connector_synced',
    details: `${connector.name}: синхронизировано ${count} записей`,
  })

  return { entries: newEntries }
}
