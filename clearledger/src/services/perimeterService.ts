/**
 * Клиент `/api/perimeter/*` — «Периметр»: три слоя обязательств вне баланса.
 *
 * Первые два слоя считает «Бухгалтерия» (`/api/books/off-balance*`), и здесь они
 * берутся её же ручками — второй реализации у цифры быть не должно. Своё у продукта
 * только третье: договорённости, обещания и решения, которых в учёте нет.
 */
import { del, get, post, put } from './apiClient'

/** Запись третьего слоя. Суммы может не быть: не всё меряется деньгами. */
export interface PerimeterRecord {
  id: string
  kind: string; kindLabel: string
  direction: string; directionLabel: string
  title: string; details: string | null
  counterpartyId: string | null; counterparty: string | null
  amount: number | null
  startedOn: string | null; dueOn: string | null
  /** Дней до срока; отрицательное — просрочено. Считает бэкенд. */
  daysLeft: number | null
  overdue: boolean
  status: string; statusLabel: string
  confidence: string; confidenceLabel: string
  source: string | null; evidence: string | null
  consequence: string | null
  /** Забалансовый счёт, на который запись встала бы при оформлении. */
  account: string | null
  createdAt: string | null; closedAt: string | null; closedNote: string | null
}

export interface PerimeterRecordIn {
  title: string
  kind: string
  direction: string
  details?: string | null
  counterpartyId?: string | null
  counterpartyName?: string | null
  amount?: number | null
  startedOn?: string | null
  dueOn?: string | null
  status: string
  confidence: string
  source?: string | null
  evidence?: string | null
  consequence?: string | null
  account?: string | null
  closedNote?: string | null
}

export interface PerimeterDicts {
  kinds: { key: string; label: string }[]
  directions: { key: string; label: string }[]
  statuses: { key: string; label: string }[]
  confidence: { key: string; label: string }[]
}

export interface PerimeterOverview {
  layers: {
    key: string; no: number; title: string; hint: string
    /** Официальный слой приезжает из учёта, неофициальный записан человеком. */
    official: boolean
    count: number; amount: number; empty: boolean; note: string
  }[]
  byKind: { key: string; label: string; count: number; amount: number }[]
  byConfidence: { key: string; label: string; count: number; amount: number }[]
  overdue: PerimeterRecord[]
  soon: PerimeterRecord[]
  /** Записи с проставленным счётом, по которому в учёте пусто: пора оформлять. */
  toFormalize: PerimeterRecord[]
  withoutAmount: number
  activeCount: number
  totalCount: number
}

export interface PerimeterParty {
  counterparty: string; counterpartyId: string | null
  active: number; closed: number; amount: number; overdue: number
  nearest: string | null; kinds: string[]
}

export const getPerimeterDicts = (companyId: string) =>
  get<PerimeterDicts>(`/api/perimeter/dictionaries?company_id=${companyId}`)

export const getPerimeterOverview = (companyId: string) =>
  get<PerimeterOverview>(`/api/perimeter/overview?company_id=${companyId}`)

export const getPerimeterRecords = (
  companyId: string, f: { status?: string; kind?: string; direction?: string; q?: string } = {},
) => get<{ rows: PerimeterRecord[]; count: number }>(
  `/api/perimeter/records?company_id=${companyId}`
  + (f.status ? `&status=${f.status}` : '')
  + (f.kind ? `&kind=${f.kind}` : '')
  + (f.direction ? `&direction=${f.direction}` : '')
  + (f.q ? `&q=${encodeURIComponent(f.q)}` : ''))

export const createPerimeterRecord = (companyId: string, body: PerimeterRecordIn) =>
  post<PerimeterRecord>(`/api/perimeter/records?company_id=${companyId}`, body)

export const updatePerimeterRecord = (
  companyId: string, id: string, body: PerimeterRecordIn,
) => put<PerimeterRecord>(`/api/perimeter/records/${id}?company_id=${companyId}`, body)

export const deletePerimeterRecord = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(`/api/perimeter/records/${id}?company_id=${companyId}`)

export const getPerimeterParties = (companyId: string) =>
  get<{ rows: PerimeterParty[] }>(`/api/perimeter/by-counterparty?company_id=${companyId}`)
