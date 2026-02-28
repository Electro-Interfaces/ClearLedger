/**
 * CRUD для конфигов коннекторов.
 * Dual-mode: localStorage (demo) / API (production).
 * Demo-sync: simulateSync генерирует тестовые записи через intake.
 * Реальный polling — задача Слоя 2 (Python + cron).
 */

import type { Connector, DataEntry } from '@/types'
import { isApiEnabled, get, post, patch, del } from './apiClient'
import { apiToConnector, connectorToApi, type ApiConnector } from './apiMappers'
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

// ---- Demo Sync ----

const EMAIL_SUBJECTS = [
  'Акт сверки за январь 2026',
  'Счёт-фактура №1234 от 15.01.2026',
  'Накладная на поставку ГСМ',
  'Договор поставки №45-2026',
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
  'Транзакция #TX-2026-001',
  'Отгрузка #SHP-45678',
  'Заявка на поставку #REQ-99',
  'Инвентаризация #INV-2026-02',
  'Приходный ордер #REC-112',
]

function randomItems<T>(arr: T[], count: number): T[] {
  const shuffled = [...arr].sort(() => Math.random() - 0.5)
  return shuffled.slice(0, count)
}

/** Симуляция синхронизации: генерирует 2-5 DataEntry */
export async function simulateSync(companyId: string, connectorId: string): Promise<{ entries: DataEntry[]; error?: string }> {
  if (isApiEnabled()) {
    try {
      const result = await post<{ entries: DataEntry[]; error?: string }>(`/api/connectors/${connectorId}/poll`, {})
      return result
    } catch (err) {
      return { entries: [], error: err instanceof Error ? err.message : String(err) }
    }
  }

  const connector = await getConnector(companyId, connectorId)
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

  // Маппинг категорий коннектора → подкатегории
  const subcategoryMap: Record<string, string> = {
    primary: 'invoices',
    operational: 'fuel-deliveries',
    financial: 'reconciliation',
    media: 'scans',
    compliance: 'licenses',
  }

  for (let i = 0; i < count; i++) {
    const categoryId = connector.categoryId || 'primary'
    const docNumber = `${Math.floor(Math.random() * 9000) + 1000}`
    const entry: DataEntry = {
      id: nextId(),
      title: templates[i] ?? `Запись ${i + 1} от ${connector.name}`,
      categoryId,
      subcategoryId: subcategoryMap[categoryId] || 'invoices',
      companyId,
      status: 'new',
      source,
      sourceLabel: `Коннектор: ${connector.name}`,
      metadata: {
        docNumber,
        docDate: now.slice(0, 10),
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
  await updateConnector(companyId, connectorId, {
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
