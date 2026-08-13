/**
 * Клиент `/api/books/*` — бухгалтерия-эталон офисного пространства и её разрезы.
 *
 * Числа считает бэкенд по регистру (`gl_entries`) и документам (`accounting_docs`):
 * фронт ничего не пересчитывает, иначе «Продажи» и «Бухгалтерия» разошлись бы в
 * выручке на копейки округления — а именно сходимость с бухгалтерией здесь и есть
 * смысл продукта.
 */
import { get } from './apiClient'

export interface BooksOverview {
  revenue: number
  vat: number
  revenueNet: number
  cost: number
  grossProfit: number
  entries: number
  firstEntry: string | null
  lastEntry: string | null
  periodsTotal: number
  periodsClosed: number
  years: { year: number; revenue: number }[]
}

export interface TurnoverRow {
  code: string
  name: string
  debit: number
  credit: number
  entries: number
}

export interface EntryRow {
  date: string
  docKind: string | null
  docTitle: string | null
  accountDt: string | null
  accountKt: string | null
  amount: number
  content: string | null
}

export interface PeriodRow {
  year: number
  month: number
  status: string
  source: string
  entries: number
  revenue: number
}

export interface DocRow {
  date: string
  number: string
  type: string
  /** Имя вида документа с сервера — словарь один на выгрузки и на экран. */
  label: string
  /** Участок учёта: sales, purchases, money, warehouse, closing. */
  section: string | null
  counterparty: string
  inn: string | null
  amount: number
  vat: number
  operation: string | null
  status: string
  /** closed — месяц закрыт в бухгалтерии, документ уже не переписать. */
  periodStatus: string
  lines: number
}

export interface DocKind {
  type: string
  label: string
  section: string | null
  count: number
  amount: number
}

/** Папка реестра — участок учёта, а не вид документа. Пустые тоже приходят. */
export interface DocSection {
  code: string
  title: string
  count: number
  amount: number
  kinds: DocKind[]
}

export interface SliceData {
  total: number
  vat: number
  net: number
  docs: number
  clients: number
  months: { month: string; amount: number; docs: number }[]
  /** id — ссылка на карточку контрагента; null у документов, что не свелись. */
  topClients: { id: string | null; name: string; inn: string | null; amount: number; docs: number }[]
  topItems: { code: string | null; name: string; amount: number; qty: number }[]
}

export const getBooksOverview = (companyId: string) =>
  get<BooksOverview>(`/api/books/overview?company_id=${companyId}`)

export const getTurnover = (companyId: string, year?: number) =>
  get<{ rows: TurnoverRow[]; total: number }>(
    `/api/books/turnover?company_id=${companyId}${year ? `&year=${year}` : ''}`)

export const getEntries = (companyId: string, opts: { year?: number; account?: string; limit?: number } = {}) =>
  get<{ rows: EntryRow[]; total: number }>(
    `/api/books/entries?company_id=${companyId}`
    + (opts.year ? `&year=${opts.year}` : '')
    + (opts.account ? `&account=${encodeURIComponent(opts.account)}` : '')
    + `&limit=${opts.limit ?? 100}`)

export const getPeriods = (companyId: string) =>
  get<{ rows: PeriodRow[] }>(`/api/books/periods?company_id=${companyId}`)

/** Период — общий фильтр рабочей области; без него ручка отдаёт всю историю. */
interface PeriodOpts { from?: string; to?: string }

const periodQuery = (o: PeriodOpts = {}) =>
  (o.from ? `&date_from=${o.from}` : '') + (o.to ? `&date_to=${o.to}` : '')

export const getDocs = (
  companyId: string, docType?: string, period?: PeriodOpts, section?: string, offset = 0,
  lineKind?: string,
) =>
  get<{ rows: DocRow[]; total: number; kinds: DocKind[]; sections: DocSection[] }>(
    `/api/books/docs?company_id=${companyId}${docType ? `&doc_type=${docType}` : ''}`
    + (section && !docType ? `&section=${section}` : '')
    + (lineKind ? `&line_kind=${lineKind}` : '')
    + periodQuery(period) + `&limit=500&offset=${offset}`)

/**
 * Весь реестр целиком — проводнику «Документы» дерево строить не из чего, пока не
 * пришли все шапки. Ручка отдаёт максимум 500 за раз, поэтому дочитываем страницами:
 * шапки лёгкие, три тысячи документов — семь запросов.
 */
export async function getAllDocs(
  companyId: string,
): Promise<{ rows: DocRow[]; sections: DocSection[] }> {
  const first = await getDocs(companyId)
  const rows = [...first.rows]
  while (rows.length < first.total) {
    const next = await getDocs(companyId, undefined, undefined, undefined, rows.length)
    if (next.rows.length === 0) break   // страховка от бесконечного цикла
    rows.push(...next.rows)
  }
  return { rows, sections: first.sections }
}

/** Разрез: `sales` — товары, `services` — услуги. Форма ответа одна. */
export const getSlice = (
  companyId: string, kind: 'sales' | 'services', opts: PeriodOpts & { top?: number } = {},
) =>
  get<SliceData>(`/api/books/${kind}?company_id=${companyId}&top=${opts.top ?? 15}`
    + periodQuery(opts))

export interface BalanceRow {
  code: string
  name: string
  kind: string | null
  offBalance: boolean
  parent: string | null
  level: number
  hasChildren: boolean
  saldoInDt: number
  saldoInKt: number
  turnoverDt: number
  turnoverKt: number
  saldoOutDt: number
  saldoOutKt: number
  entries: number
}

export interface BalanceTotals {
  saldoInDt: number; saldoInKt: number
  turnoverDt: number; turnoverKt: number
  saldoOutDt: number; saldoOutKt: number
}

export interface AccountCard {
  code: string
  name: string
  kind: string | null
  saldoInDt: number; saldoInKt: number
  turnoverDt: number; turnoverKt: number
  saldoOutDt: number; saldoOutKt: number
  total: number
  shown: number
  rows: {
    date: string; docKind: string | null; docTitle: string | null
    account: string | null; corr: string | null
    debit: number; credit: number; saldo: number; content: string | null
  }[]
  corr: { code: string; debit: number; credit: number; entries: number }[]
  months: { month: string; debit: number; credit: number }[]
}

/** ОСВ за период: сальдо на начало, обороты, сальдо на конец (с иерархией счетов). */
export const getBalance = (companyId: string, period?: PeriodOpts) =>
  get<{ rows: BalanceRow[]; totals: BalanceTotals; offBalanceTotals: BalanceTotals }>(
    `/api/books/balance?company_id=${companyId}` + periodQuery(period))

/** Карточка счёта: проводки с корреспонденцией и сальдо нарастающим итогом. */
export const getAccountCard = (companyId: string, code: string, period?: PeriodOpts) =>
  get<AccountCard>(`/api/books/account?company_id=${companyId}`
    + `&code=${encodeURIComponent(code)}` + periodQuery(period))

/**
 * Карточка контрагента — всё, что пространство знает о клиенте, одним ответом:
 * реквизиты справочника, договоры, документы, долг из регистра и что он покупает.
 * Ключ — ссылка на карточку, а не имя: по имени одно юрлицо разваливается на два.
 */
export interface CounterpartyCard {
  id: string
  name: string
  inn: string | null
  kpp: string | null
  ogrn: string | null
  kind: string | null
  fullName: string | null
  address: string | null
  phone: string | null
  email: string | null
  director: string | null
  bankAccount: string | null
  bankName: string | null
  okved: string | null
  /** Сальдо расчётов из регистра: 62 — нам должны, 60 — должны мы. */
  receivable: number
  payable: number
  byType: Record<string, { docs: number; amount: number }>
  months: { month: string; sales: number; purchases: number; paid: number }[]
  items: {
    code: string; name: string; qty: number; amount: number
    docs: number; unit: string | null
  }[]
  contracts: {
    id: string; number: string; date: string | null; type: string
    kind: string | null; closed: boolean; docs: number
  }[]
  docs: {
    id: string; date: string; type: string; label: string; number: string
    amount: number; vat: number; contract: string | null; periodStatus: string
  }[]
}

export const getCounterpartyCard = (companyId: string, counterpartyId: string) =>
  get<CounterpartyCard>(`/api/books/counterparty?company_id=${companyId}`
    + `&counterparty_id=${counterpartyId}`)

export interface SourceInfo {
  kind: string
  name: string
  loadedAt: string | null
  periodFrom: string | null
  periodTo: string | null
  datasets: { key: string; label: string; records: number }[]
  /** Состав среза по видам — документы и справочники бухгалтерии. */
  documents?: { key: string; label: string; records: number }[]
  references?: { key: string; label: string; records: number }[]
}

export interface QualityCheck {
  key: string
  label: string
  status: 'ok' | 'warn' | 'error' | 'info'
  value: string | number
  hint: string
  detail?: string | null
}

export const getSources = (companyId: string) =>
  get<{ sources: SourceInfo[] }>(`/api/books/sources?company_id=${companyId}`)

export const getQuality = (companyId: string) =>
  get<{ checks: QualityCheck[]; errors: number; warnings: number; ok: number }>(
    `/api/books/quality?company_id=${companyId}`)

export interface ModelLayer {
  key: string; code: string; title: string; desc: string
  records: number | null; unit: string; tone: 'raw' | 'clean' | 'export' | 'ref'
  /** `direct` — слой не материализован, данные приняты прямым импортом. */
  status?: string
}
export interface ModelDimension {
  key: string; label: string; field: string; cardinality: number
  fill_pct: number; canonical: boolean; grain?: string | null
  members: { label: string; count: number }[]
}
export interface DataModelResponse {
  rows: number
  layers: ModelLayer[]
  fact: {
    table: string; name: string; grain: string; rows: number
    period: { from: string | null; to: string | null }
    measures: { key: string; label: string; value: number; unit: string; agg: string }[]
  } | null
  dimensions: ModelDimension[]
  quality: {
    fields: { field: string; label: string; role: string; fill_pct: number }[]
    canonicalization: { name: string; from: string; to: string; members: number | null; coverage_pct: number | null }[]
  } | null
}

/** Модель данных бухгалтерии: слои, звезда, качество — как «Нормализация» у сетевых. */
export const getDataModel = (companyId: string) =>
  get<DataModelResponse>(`/api/books/model?company_id=${companyId}`)

export interface DatasetView {
  key: string; label: string; table: string; records: number; link: string
  period: { from: string | null; to: string | null }
  fields: { field: string; label: string; fill_pct: number; distinct: number }[]
  top: { label: string; count: number }[]
}

/** Витрина одного набора данных нормализованного слоя. */
export const getDataset = (companyId: string, key: string) =>
  get<DatasetView>(`/api/books/dataset?company_id=${companyId}&key=${key}`)

// ── Аналитический слой: взаиморасчёты и налог ───────────────────────────────
// Считает бэкенд по сальдо и оборотам из 1С, а не наши проводки: субконто в
// регистре через COM недоступно, у проводки нет стороны расчётов.

export interface SettlementRow {
  account: string
  accountName: string | null
  counterparty: string | null
  contract: string | null
  debit: number
  credit: number
  /** Дебет минус кредит: положительное — должны нам, отрицательное — аванс. */
  net: number
}

export interface SettlementsData {
  /** Дата среза сальдо: остаток не пересчитывается, он снят на этот день. */
  asOf: string | null
  rows: SettlementRow[]
  totals: { debit: number; credit: number }
  months: { month: string; grew: number; closed: number }[]
}

export type SettlementKind = 'receivable' | 'payable' | 'other'

export const getSettlements = (companyId: string, kind: SettlementKind) =>
  get<SettlementsData>(`/api/books/settlements?company_id=${companyId}&kind=${kind}`)

export interface VatRow {
  date: string | null
  number: string | null
  counterparty: string | null
  inn: string | null
  kpp: string | null
  amount: number
  vat: number
  rate: string | null
  invoice: string | null
  registrar: string | null
  operationCode: string | null
}

export interface VatData {
  total: number
  amount: number
  vat: number
  kinds: { kind: string; count: number; amount: number; vat: number }[]
  months: { month: string; count: number; amount: number; vat: number }[]
  rows: VatRow[]
}

export type VatKind = 'issued' | 'received' | 'claimed'

export const getVat = (companyId: string, kind: VatKind, period?: PeriodOpts) =>
  get<VatData>(`/api/books/vat?company_id=${companyId}&kind=${kind}` + periodQuery(period))
