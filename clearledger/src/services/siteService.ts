/**
 * «Сайт»: что происходит на публичной витрине и в кабинете клиента.
 *
 * Данные ведёт сам сайт (elsyplus.ru) — здесь только чтение через Ядро. Ответ
 * всегда одной формы: содержимое плюс состояние связи, потому что «пусто» и
 * «связи нет» — разные ответы, и человек должен видеть, какой из них перед ним.
 */
import { del, get, post } from './apiClient'

/** Общая обёртка ответа: данные и состояние связи с сайтом. */
export interface SiteFeed<T> {
  items: T[]
  connected: boolean
  reason: string | null
  url?: string
}

/** Обращение из кабинета сайта. */
export interface SiteRequest {
  id?: number | string
  email?: string
  company?: string | null
  product?: string | null
  kind?: string | null
  message?: string | null
  created_at?: number | string
}

/** Человек, заведённый в кабинете сайта. */
export interface SiteCabinet {
  email: string
  level?: string
  company?: string | null
  note?: string | null
  created_at?: number | string
  last_login_at?: number | string | null
}

/** Запись журнала демо-стендов. */
export interface SiteDemoEntry {
  id?: number | string
  email?: string
  demo_id?: string
  ip?: string | null
  created_at?: number | string
}

export interface SiteSummary {
  requests: number
  cabinets: number
  demos: number
  connected: boolean
  reason: string | null
  url?: string
}

export const getSummary = (companyId: string) =>
  get<SiteSummary>('/site/summary', { company_id: companyId })

export const getRequests = (companyId: string) =>
  get<SiteFeed<SiteRequest>>('/site/requests', { company_id: companyId })

export const getCabinets = (companyId: string) =>
  get<SiteFeed<SiteCabinet>>('/site/cabinets', { company_id: companyId })

export const getDemos = (companyId: string) =>
  get<SiteFeed<SiteDemoEntry>>('/site/demos', { company_id: companyId })

/** Уровни доступа кабинета словами — на сайте они кодами. */
export const LEVEL_LABELS: Record<string, string> = {
  visitor: 'Гость',
  guest: 'Гость',
  prospect: 'Потенциальный клиент',
  client: 'Клиент',
  admin: 'Администратор',
}

/** Время сайта приходит миллисекундами (SQLite), а не строкой ISO. */
export function siteTime(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value) : new Date(
    /^\d+$/.test(String(value)) ? Number(value) : String(value))
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

// ── Управление: мастер живёт в пространстве ──────────────────────────────────
// Кто вхож в кабинет и какие стенды показываем — решение пространства. Сайт эти
// записи читает при входе, а правятся они здесь.

/** Доступ клиента в кабинет сайта. */
export interface CabinetUser {
  id: string
  email: string
  level: string
  counterpartyId: string | null
  counterpartyName: string | null
  counterpartyInn: string | null
  /** Пусто = открыты все стенды. */
  demos: string[]
  note: string | null
  isActive: boolean
  createdAt: string | null
}

export interface CabinetUserInput {
  email: string
  level: string
  counterparty_id?: string | null
  demos?: string[]
  note?: string | null
  is_active?: boolean
}

/** Демо-стенд из каталога пространства. */
export interface DemoStand {
  id: string
  code: string
  title: string
  description: string | null
  upstreamUrl: string | null
  externalUrl: string | null
  landing: string | null
  isEnabled: boolean
  sort: number
}

export interface DemoStandInput {
  code: string
  title: string
  description?: string | null
  upstream_url?: string | null
  external_url?: string | null
  landing?: string | null
  is_enabled?: boolean
  sort?: number
}

export const getCabinetUsers = (companyId: string) =>
  get<{ items: CabinetUser[] }>('/site/cabinet-users', { company_id: companyId })

export const saveCabinetUser = (companyId: string, input: CabinetUserInput) =>
  post<CabinetUser>(`/site/cabinet-users?company_id=${encodeURIComponent(companyId)}`, input)

export const dropCabinetUser = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(
    `/site/cabinet-users/${id}?company_id=${encodeURIComponent(companyId)}`)

export const getDemoStands = (companyId: string) =>
  get<{ items: DemoStand[] }>('/site/demo-stands', { company_id: companyId })

export const saveDemoStand = (companyId: string, input: DemoStandInput) =>
  post<DemoStand>(`/site/demo-stands?company_id=${encodeURIComponent(companyId)}`, input)
