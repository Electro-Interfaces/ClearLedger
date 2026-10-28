/**
 * «Бухгалтерия» пространства — чтение сопряжений выгрузки с карточками.
 *
 * Сторона бухгалтерии приезжает выгруженными отчётами и живёт строками-источниками;
 * сторона пространства — наши карточки договоров, контрагентов и площадок. Сервис
 * только читает: правки и загрузка новых отчётов в этот срез не входят.
 *
 * Статусы — две независимые оси (сопряжение и проверка), поэтому и в типах они
 * раздельные поля, а не один флаг «сверено».
 */
import { get } from './apiClient'

/** Опознана ли строка источника. */
export type LinkStatus = 'matched' | 'related' | 'unmatched' | 'candidate'
/** Что сверено. `stale` — карточка менялась после проверки. */
export type VerificationStatus = 'verified' | 'partial' | 'differences' | 'not_checked' | 'stale'

export interface AccountingDifference {
  field: string
  label: string
  source: string
  space: string
}

export interface AccountingCard {
  id: string
  exists: boolean
  number?: string
  date?: string
  title?: string | null
  type?: string
  type_code?: string | null
  basis?: string | null
  valid_until?: string | null
  signed?: boolean | null
  signed_at?: string | null
  counterparty_id?: string
  counterparty_name?: string
  counterparty_inn?: string
  counterparty_kpp?: string
  organization_id?: string
  locations?: { id: string; code: string; name: string }[]
}

export interface AccountingLink {
  entity_type: string
  entity_id: string
  relation: string
  status: LinkStatus
  status_label: string
  verification: VerificationStatus
  verification_label: string
  stale: boolean
  subject_status: string
  snapshot_at: string
  checked_fields: string[]
  checked_values: Record<string, unknown>
  current_values: Record<string, unknown>
  checked_hash: string
  current_hash: string
  differences: AccountingDifference[]
  inn_kpp_checked: boolean
  original_document_checked: boolean
  card: AccountingCard
  location_ids: string[]
}

export interface AccountingRecord {
  id: string
  status: LinkStatus
  status_label: string
  verification: VerificationStatus
  verification_label: string
  counterparty_name: string
  contract_label: string
  kind: string
  reason: string
  entry_status: string
  layer: string
  source_file: string
  source_sheet: string
  source_rows: string
  source_period: string
  source_as_of: string
  batch_id: string
  station_hint: string
  candidates: string
  links_count: number
  differences_count: number
  stale_count: number
  location_ids: string[]
  cards: AccountingCard[]
  card_labels: string[]
}

export interface AccountingRecordCard extends AccountingRecord {
  source_side: {
    counterparty: string
    contract: string
    kind: string
    period: string
    as_of: string
    file: string
    sheet: string
    rows: string
    sha256: string
    key: string
    key_type: string
    record_kind: string
    station_hint: string
    /** Признака проведения в 1С выгрузка не содержит — остаётся неизвестным. */
    posted: boolean | null
    original_document: boolean | null
  }
  links: AccountingLink[]
}

export interface AccountingSummary {
  source_rows: number
  by_status: Partial<Record<LinkStatus, number>>
  by_verification: Partial<Record<VerificationStatus, number>>
  differences: number
  stale: number
  linked_contracts: number
  linked_locations: number
  missing_cards: number
  counterparties_in_source: number
  contracts_in_source: number
  space: {
    contracts: number
    counterparties: number
    locations: number
    contracts_without_source: number
  }
  periods: string[]
  as_of: string[]
  scope: string
}

export interface AccountingSourceBatch {
  batch_id: string
  file: string
  sheet: string
  period: string
  as_of: string
  sha256: string
  key_type: string
  rows: number
  by_status: Partial<Record<LinkStatus, number>>
  loaded_at: string | null
  /** Дата формирования файла в 1С неизвестна — выдумывать её нельзя. */
  exported_at: string | null
}

export interface AccountingObjectContract {
  contract: AccountingCard
  source: {
    record_id: string
    status: LinkStatus
    status_label: string
    verification: VerificationStatus
    counterparty: string
    contract_label: string
    file: string
    rows: string
    as_of: string
  }[]
}

export interface AccountingObject {
  id: string
  code: string
  name: string
  address: string
  status: string
  rent: AccountingObjectContract[]
  energy: AccountingObjectContract[]
  other: AccountingObjectContract[]
  contracts_count: number
  with_source: number
  without_source: number
  unchecked: number
  has_rent: boolean
  has_energy: boolean
}

const base = '/api/accounting/space'

export const getAccountingSummary = (companyId: string, organizationId?: string) =>
  get<AccountingSummary>(`${base}/summary`, { company_id: companyId, organization_id: organizationId })

export const getAccountingRecords = (companyId: string, params: {
  status?: string; verification?: string; locationId?: string; search?: string
  limit?: number; offset?: number; organizationId?: string
} = {}) => get<{ total: number; items: AccountingRecord[] }>(`${base}/records`, {
  company_id: companyId, status: params.status, verification: params.verification,
  location_id: params.locationId, search: params.search,
  limit: params.limit, offset: params.offset, organization_id: params.organizationId,
})

/**
 * Весь отбор, а не первая страница.
 *
 * Плитки, таблица и выгрузка обязаны показывать одни и те же строки: пока экран
 * брал первые 200, «не сопряжено: 135» и список из 100 строк расходились, и человек
 * не мог понять, чего он не видит. Страницы складываются, пока не набран `total`.
 */
export async function getAllAccountingRecords(companyId: string, params: {
  status?: string; verification?: string; locationId?: string; search?: string
  organizationId?: string
} = {}): Promise<{ total: number; items: AccountingRecord[] }> {
  const page = 500
  const first = await getAccountingRecords(companyId, { ...params, limit: page, offset: 0 })
  const items = [...first.items]
  while (items.length < first.total && items.length) {
    const next = await getAccountingRecords(companyId, { ...params, limit: page, offset: items.length })
    if (!next.items.length) break
    items.push(...next.items)
  }
  return { total: first.total, items }
}

export const getAccountingRecord = (companyId: string, entryId: string, organizationId?: string) =>
  get<AccountingRecordCard>(`${base}/records/${entryId}`, {
    company_id: companyId, organization_id: organizationId,
  })

export const getAccountingObjects = (companyId: string, params: {
  search?: string; onlyGaps?: boolean; organizationId?: string
} = {}) => get<{ total: number; items: AccountingObject[] }>(`${base}/objects`, {
  company_id: companyId, search: params.search,
  only_gaps: params.onlyGaps ? 'true' : undefined, organization_id: params.organizationId,
})

export const getAccountingSources = (companyId: string, organizationId?: string) =>
  get<{ items: AccountingSourceBatch[]; scope: string }>(`${base}/sources`, {
    company_id: companyId, organization_id: organizationId,
  })

/** Сопряжения одной карточки — для бейджа в её собственном экране. */
export const getAccountingEntityLinks = (companyId: string, entityType: string, entityId: string) =>
  get<{ items: {
    record_id: string; status: LinkStatus; status_label: string
    verification: VerificationStatus; verification_label: string; stale: boolean
    relation: string; checked_fields: string[]; differences: AccountingDifference[]
    source: { counterparty: string; contract: string; file: string; sheet: string
      rows: string; period: string; as_of: string }
  }[] }>(`${base}/links`, {
    company_id: companyId, entity_type: entityType, entity_id: entityId,
  })
