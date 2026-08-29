/**
 * «Сайт»: что происходит на публичной витрине и в кабинете клиента.
 *
 * Данные ведёт сам сайт (elsyplus.ru) — здесь только чтение через Ядро. Ответ
 * всегда одной формы: содержимое плюс состояние связи, потому что «пусто» и
 * «связи нет» — разные ответы, и человек должен видеть, какой из них перед ним.
 */
import { del, get, post, put } from './apiClient'

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

/** Заявка с формы витрины. */
export interface SiteLead {
  id: number
  created_at: number
  name: string | null
  company: string | null
  email: string | null
  phone: string | null
  interest: string | null
  product: string | null
  message: string | null
  status: string
}

/** Состояния заявки словами. Коды держит сайт. */
export const LEAD_STATUS_LABELS: Record<string, string> = {
  new: 'Новая',
  in_work: 'В работе',
  quoted: 'КП отправлено',
  closed: 'Закрыта',
}

export interface SiteSummary {
  requests: number
  leads: number
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

export const getLeads = (companyId: string) =>
  get<SiteFeed<SiteLead>>('/site/leads', { company_id: companyId })

export const setLeadStatus = (companyId: string, id: number, status: string) =>
  post<{ ok?: boolean }>(
    `/site/leads/${id}/status?company_id=${encodeURIComponent(companyId)}`, { status })

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

/** Пространство, развёрнутое клиенту: его контур и состояние. */
export interface ClientSpace {
  id: string
  slug: string
  domain: string
  status: string
  note: string | null
  counterpartyId: string
  counterpartyName: string | null
}

export interface ClientSpaceInput {
  counterparty_id: string
  slug: string
  domain?: string
  status?: string
  note?: string | null
}

/** Состояния контура словами. Пока не `active` — кнопки в кабинете нет. */
export const SPACE_STATUS_LABELS: Record<string, string> = {
  planned: 'Решено развернуть',
  deploying: 'Разворачивается',
  active: 'Работает',
  suspended: 'Приостановлено',
}

export const getClientSpaces = (companyId: string) =>
  get<{ items: ClientSpace[] }>('/site/client-spaces', { company_id: companyId })

export const saveClientSpace = (companyId: string, input: ClientSpaceInput) =>
  post<ClientSpace>(`/site/client-spaces?company_id=${encodeURIComponent(companyId)}`, input)

// ── Витрина сайта ────────────────────────────────────────────────
// Правки текстов и цен лежат на сайте, правятся отсюда. Состав разделов
// говорит сам сайт: появится там новый — он приедет сюда без правки пространства.

export interface ContentSection {
  key: string
  updated_at?: number | null
  updated_by?: string | null
  size?: number | null
}

export interface SiteContent {
  keys: string[]
  sections: ContentSection[]
  values: Record<string, unknown>
  connected: boolean
  reason: string | null
  url?: string
}

/** Разделы витрины словами. Незнакомый ключ показываем как есть. */
export const CONTENT_LABELS: Record<string, string> = {
  products: 'Продукты',
  pricing: 'Цены',
  news: 'Новости и статьи',
  faq: 'Вопросы',
  settings: 'Контакты и SEO',
}

export const getContent = (companyId: string) =>
  get<SiteContent>('/site/content', { company_id: companyId })

export const saveContent = (companyId: string, key: string, value: unknown) =>
  put<{ ok?: boolean }>(
    `/site/content/${encodeURIComponent(key)}?company_id=${encodeURIComponent(companyId)}`,
    { value })
