/**
 * Клиент `/api/books/*` — бухгалтерия-эталон офисного пространства и её разрезы.
 *
 * Числа считает бэкенд по регистру (`gl_entries`) и документам (`accounting_docs`):
 * фронт ничего не пересчитывает, иначе «Продажи» и «Бухгалтерия» разошлись бы в
 * выручке на копейки округления — а именно сходимость с бухгалтерией здесь и есть
 * смысл продукта.
 */
import { get, post } from './apiClient'

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
  /** id документа — по паре «номер + дата» его не найти, она не уникальна. */
  id: string
  date: string
  number: string
  type: string
  /** Имя вида документа с сервера — словарь один на выгрузки и на экран. */
  label: string
  /** Участок учёта: sales, purchases, money, warehouse, closing. */
  section: string | null
  counterparty: string
  inn: string | null
  /** Ссылка на карточку контрагента; null — документ не сведён со справочником. */
  counterpartyId: string | null
  amount: number
  vat: number
  operation: string | null
  status: string
  /** closed — месяц закрыт в бухгалтерии, документ уже не переписать. */
  periodStatus: string
  lines: number
  /**
   * Оплата счёта покупателю. null — оплата НЕИЗВЕСТНА (у не-счетов вопрос
   * неприменим, у счёта нет записи в регистре «Оплата счетов»), 0 — регистр знает
   * счёт и оплаты по нему нет.
   */
  paid: number | null
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
  /** Доля товаров и услуг внутри разреза — по строкам документов. */
  byKind: { goods: number; service: number }
  /** id — ссылка на карточку контрагента; null у документов, что не свелись. */
  topClients: {
    id: string | null; name: string; inn: string | null; amount: number; docs: number
    /** Крайние даты покупок — по ним видно молчащих. */
    first: string | null; last: string | null
  }[]
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
  get<{
    rows: DocRow[]; total: number; kinds: DocKind[]; sections: DocSection[]
    /** Покрытие регистра оплат: у скольких показанных счетов связь вообще есть. */
    paidKnown?: number; paidTotal?: number
  }>(
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
  // Дедуп по id: страницы режутся внутри дня, и стоит серверу отдать строки в другом
  // порядке — один документ приедет дважды, а другой не приедет. Сумма отбора при
  // дубле завышается молча, поэтому страховка здесь, а не только в сортировке.
  const seen = new Set<string>()
  return {
    rows: rows.filter((r) => (r.id && seen.has(r.id) ? false : (seen.add(r.id), true))),
    sections: first.sections,
  }
}

/**
 * Все документы вида за период — с дочитыванием страниц.
 *
 * `getDocs` отдаёт максимум 500 строк, а экраны «Счета», «Воронка» и «Реализации»
 * считают по полученному массиву ИТОГИ. Пока счетов меньше пятисот, разницы нет; на
 * шестистах экран молча покажет заниженную сумму и ложную конверсию воронки. Поэтому
 * там, где из строк выводится цифра, набираем множество целиком.
 */
export async function getDocsAll(
  companyId: string, docType: string, period?: PeriodOpts, lineKind?: string,
): Promise<{ rows: DocRow[]; total: number; paidKnown: number }> {
  const first = await getDocs(companyId, docType, period, undefined, 0, lineKind)
  const rows = [...first.rows]
  let paidKnown = first.paidKnown ?? 0
  while (rows.length < first.total) {
    const next = await getDocs(companyId, docType, period, undefined, rows.length, lineKind)
    if (!next.rows.length) break            // страховка от бесконечного цикла
    rows.push(...next.rows)
    paidKnown += next.paidKnown ?? 0
  }
  const seen = new Set<string>()
  return {
    rows: rows.filter((r) => (r.id && seen.has(r.id) ? false : (seen.add(r.id), true))),
    total: first.total,
    paidKnown,
  }
}

/** Разрез реализации: всё целиком, только товары или только услуги. Ответ один. */
export type RevKind = 'all' | 'goods' | 'service'

export const getRevenue = (
  companyId: string, kind: RevKind, opts: PeriodOpts & { top?: number } = {},
) =>
  get<SliceData>(`/api/books/revenue?company_id=${companyId}&kind=${kind}`
    + `&top=${opts.top ?? 15}` + periodQuery(opts))

/**
 * Ассортимент (или клиентская база) с помесячным рядом: из ряда считается XYZ —
 * стабильность спроса, а у позиций рядом лежат закупки, то есть себестоимость.
 */
export interface AssortmentRow {
  key: string
  /** Только у позиций. */
  code?: string
  /** Только у клиентов; null — документ не сведён со справочником. */
  id?: string | null
  name: string
  /** Оборот: у клиента — `amount`, у позиции — `soldAmount`. */
  amount?: number
  soldQty?: number
  soldAmount?: number
  boughtQty?: number
  boughtAmount?: number
  /** Те же суммы БЕЗ НДС — маржа считается по ним: на 90.02.1 налога нет. */
  soldNet?: number
  boughtNet?: number
  docs: number
  first: string | null
  last: string | null
  months: { month: string; amount: number }[]
  /** Стабильность спроса — считается по канону пространства (пороги как у сети). */
  cv: number | null
  xyz: 'X' | 'Y' | 'Z' | '—'
  trend: 'up' | 'down' | 'flat'
  trendPct: number | null
  monthsLive: number
  /** Месяцев, в которых была продажа, и класс частоты — вторая ось матрицы. */
  saleMonths: number
  freq: 'once' | 'few' | 'regular'
}

export const getAssortment = (
  companyId: string, by: 'item' | 'client', period?: PeriodOpts,
) =>
  get<{ by: string; rows: AssortmentRow[]; cost: number | null; costBasis?: string }>(
    `/api/books/assortment?company_id=${companyId}&by=${by}` + periodQuery(period))

/** Остатки по номенклатуре: приход − расход по строкам документов. */
export interface StockData {
  rows: {
    code: string; name: string
    boughtQty: number; boughtAmount: number; soldQty: number; soldAmount: number
    restQty: number; restAmount: number; avgBuy: number
    daysOfSupply: number | null
    firstBuy: string | null; lastBuy: string | null; lastSale: string | null
    lastMove: string | null; idleDays: number | null
    /** Позицию хоть раз продавали — этим товар отличается от закупки для себя. */
    everSold: boolean
  }[]
  restAmount: number
  positions: number
  goodsAmount: number
  goodsPositions: number
  boughtTotal: number
  registerIntake: number
  negative: number
  negativeQty: number
  idle: number
  idleAmount: number
  /** Сальдо счёта 41 — контроль расчётного остатка. */
  register: number
}

export const getStock = (companyId: string) =>
  get<StockData>(`/api/books/stock?company_id=${companyId}`)

/** Поставщики: объём, зависимость и разброс цен на одну позицию. */
export interface SuppliersData {
  rows: {
    id: string | null; name: string; inn: string | null
    amount: number; docs: number; positions: number
    first: string | null; last: string | null
  }[]
  spread: {
    code: string; name: string; suppliers: number
    minPrice: number; maxPrice: number; avgPrice: number; qty: number
    minName: string; maxName: string
    /** Разрыв больше пятикратного: обычно разные единицы измерения, а не переплата. */
    suspicious: boolean
  }[]
  total: number
  topShare: number
  top3Share: number
}

export const getSuppliers = (companyId: string, period?: PeriodOpts) =>
  get<SuppliersData>(`/api/books/suppliers?company_id=${companyId}` + periodQuery(period))

/** Проверки качества данных, от которых зависят цифры «Реализации». */
export interface RevenueQuality {
  checks: { key: string; title: string; why: string; count: number }[]
  salesDocs: number
  problems: number
}

export const getRevenueQuality = (companyId: string) =>
  get<RevenueQuality>(`/api/books/revenue-quality?company_id=${companyId}`)

/** Реестр старения долга: сколько, чьё и сколько дней. */
export interface ArAging {
  buckets: { key: string; label: string; count: number; amount: number }[]
  clients: {
    id: string | null; name: string; invoices: number; rest: number
    maxAge: number; oldest: string | null
  }[]
  rows: {
    id: string; number: string; date: string; counterparty: string
    counterpartyId: string | null; amount: number; paid: number | null
    lastPaidAt: string | null; rest: number; age: number; bucket: string
  }[]
  openAmount: number
  openCount: number
  unknownCount: number
  unknownAmount: number
  registerDebit: number
  registerCredit: number
  asOf: string
  ageBasis: string
}

export const getArAging = (companyId: string) =>
  get<ArAging>(`/api/books/ar-aging?company_id=${companyId}`)

/** Кривая инкассации: доля счетов месяца, собранная к дню 30/60/90/180. */
export interface CollectionCurve {
  months: {
    month: string; billed: number; invoices: number
    d30: number; d60: number; d90: number; d180: number
    pct30: number | null; pct60: number | null; pct90: number | null; pct180: number | null
    /** Меньше пяти счетов в месяце: доля по такому числу — не статистика. */
    thin: boolean
  }[]
  avg30: number; avg60: number; avg90: number; avg180: number
  billed: number
}

export const getCollectionCurve = (companyId: string) =>
  get<CollectionCurve>(`/api/books/collection-curve?company_id=${companyId}`)

/** Реализации как сделки: сумма без НДС, себестоимость по строкам, маржа. */
export interface DealsData {
  rows: {
    id: string; number: string; date: string; counterparty: string
    counterpartyId: string | null; amount: number; net: number
    cost: number | null; lines: number; unknownLines: number
    margin: number | null; marginPct: number | null
  }[]
  count: number
  net: number
  withMargin: number
  marginTotal: number
  netWithMargin: number
  lowMargin: number
}

export const getDeals = (companyId: string, period?: PeriodOpts) =>
  get<DealsData>(`/api/books/deals?company_id=${companyId}` + periodQuery(period))

/** Счета, за которыми не пошла отгрузка. */
export interface BacklogData {
  rows: {
    counterparty: string; counterpartyId: string | null
    invoices: number; invoiced: number; sales: number; shipped: number
    firstInvoice: string | null; lastInvoice: string | null
    gap: number; shippedPct: number | null; daysSinceLast: number | null
  }[]
  invoiced: number
  shipped: number
  silentCount: number
  silentAmount: number
}

export const getBacklog = (companyId: string) =>
  get<BacklogData>(`/api/books/backlog?company_id=${companyId}`)

/** Концентрация выручки: HHI и доли лидеров, по годам. */
export interface ConcentrationStats {
  clients: number
  hhi: number | null
  cr1: number | null
  cr3: number | null
  cr5: number | null
  amount?: number
}

export interface ConcentrationData {
  total: ConcentrationStats
  years: (ConcentrationStats & { year: string })[]
  levels: { low: number; high: number }
}

export const getConcentration = (companyId: string) =>
  get<ConcentrationData>(`/api/books/concentration?company_id=${companyId}`)

/** Сроки оплаты счетов: связка «счёт ↔ платёж» из регистра «Оплата счетов». */
export interface PaymentTerms {
  rows: {
    id: string; number: string; date: string; paidAt: string
    counterparty: string; counterpartyId: string | null; amount: number; days: number
    /** Сколько платежей закрыло счёт: срок считается по последнему. */
    payments: number
  }[]
  buckets: { key: string; label: string; count: number; amount: number }[]
  clients: {
    id: string | null; name: string; invoices: number; amount: number
    avgDays: number; maxDays: number
  }[]
  /** Счетов с оплатой (не платежей — счёт может быть закрыт несколькими). */
  total: number
  payments: number
  /** Платежи, ссылающиеся на документ, которого в выгрузке нет. */
  orphanPayments: number
  orphanAmount: number
  avgDays: number | null
  medianDays: number
  amount: number
}

export const getPaymentTerms = (companyId: string, period?: PeriodOpts) =>
  get<PaymentTerms>(`/api/books/payment-terms?company_id=${companyId}` + periodQuery(period))

/** Движение денег по банковским документам: приход, расход, накопленный остаток. */
export interface CashflowData {
  months: {
    month: string; inflow: number; outflow: number
    inDocs: number; outDocs: number; net: number; balance: number
  }[]
  payers: { name: string; id: string | null; inflow: number; docs: number; last: string }[]
  payees: { name: string; id: string | null; outflow: number; docs: number; last: string }[]
  inflow: number
  outflow: number
  /** Обороты счёта 51 — контроль: расхождение = движение без документа. */
  registerIn: number
  registerOut: number
}

export const getCashflow = (companyId: string) =>
  get<CashflowData>(`/api/books/cashflow?company_id=${companyId}`)

/** Продажи в разрезе договоров; строка с id === null — документы без договора. */
export interface ContractSales {
  rows: {
    id: string | null; number: string | null; date: string | null
    kind: string | null; settlementKind: string | null
    /** null у строки «без договора»: там контрагент не один. */
    counterparty: string | null
    counterparties: number
    sales: number; salesDocs: number; invoices: number; invoiceDocs: number
    first: string | null; last: string | null
  }[]
  /** Договоры, по которым были ОТГРУЗКИ. */
  withContract: number
  /** Договоры, по которым есть только счета. */
  withInvoicesOnly: number
  salesWithContract: number
  salesTotal: number
}

export const getContractSales = (companyId: string, period?: PeriodOpts) =>
  get<ContractSales>(`/api/books/contract-sales?company_id=${companyId}` + periodQuery(period))

/** Сверка «Реализации» с регистром: документы против оборота 90.01.1 помесячно. */
export interface RevenueCheck {
  months: {
    month: string; docs: number; docsCount: number; register: number
    diff: number; periodStatus: string
  }[]
  totalDocs: number
  totalRegister: number
  diff: number
  broken: string[]
}

export const getRevenueCheck = (companyId: string) =>
  get<RevenueCheck>(`/api/books/revenue-check?company_id=${companyId}`)

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
  /** Сальдо расчётов из САЛЬДО ИСТОЧНИКА с субконто: 62 — нам должны, 60 — должны мы. */
  receivable: number
  payable: number
  /** Аванс — не «отрицательный долг»: он лежит на другой стороне того же счёта. */
  advanceIn: number
  advanceOut: number
  otherDebit: number
  otherCredit: number
  loanOut: number
  loanIn: number
  accountable: number
  debtAsOf: string | null
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

/**
 * Строка списка контрагентов с цифрами: обороты, оплаты, долг, последний документ.
 * Считается по документам и сальдо источника — тем же, чем живут карточка и
 * «Взаиморасчёты», поэтому цифра в списке и в карточке всегда одна.
 */
export interface CounterpartyStats {
  id: string
  name: string
  inn: string | null
  kind: string | null
  sales: number
  purchases: number
  paidIn: number
  paidOut: number
  docs: number
  lastDoc: string | null
  /** Долг БРУТТО: аванс отдельно, потому что это другое обязательство. */
  receivable: number
  payable: number
  advanceIn: number
  advanceOut: number
  /** Прочие расчёты (76), займы (58 и 66/67), подотчёт (71) — их не смотрели вовсе. */
  otherDebit: number
  otherCredit: number
  loanOut: number
  loanIn: number
  accountable: number
  contracts: number
}

/** Документ целиком: шапка, строки и его проводки — для просмотрщика. */
export interface DocumentCard {
  id: string
  type: string
  label: string
  number: string
  date: string
  amount: number
  vat: number
  status: string
  periodStatus: string
  operation: string | null
  counterpartyName: string
  counterpartyInn: string | null
  counterparty: { id: string; name: string; inn: string | null } | null
  contract: { number: string; date: string | null; type: string } | null
  externalNumber: string | null
  externalDate: string | null
  lines: {
    code: string | null; name: string; kind: string
    qty: number; price: number; amount: number; vat: number
  }[]
  entries: {
    date: string; accountDt: string | null; accountKt: string | null
    amount: number; content: string | null
  }[]
  meta: Record<string, unknown>
}

export const getDocumentCard = (companyId: string, docId: string) =>
  get<DocumentCard>(`/api/books/document?company_id=${companyId}&doc_id=${docId}`)

/** Месяц акта сверки: обороты по субконто и сальдо нарастающим итогом. */
export interface ActMonth {
  month: string
  debit: number
  credit: number
  saldo: number
}

export interface ActSection {
  /** Сторона расчётов: `receivable` — счёт 62 (нам должны), `payable` — 60 (мы должны). */
  kind: 'receivable' | 'payable'
  account: string
  title: string
  opening: number
  closing: number
  debitTotal: number
  creditTotal: number
  months: ActMonth[]
  /** Документы за период — расшифровка, а не источник итогов. */
  docs: { id: string; date: string; type: string; label: string; number: string; amount: number }[]
}

export interface ActData {
  counterparty: { id: string; name: string; inn: string | null; kpp: string | null }
  periodFrom: string | null
  periodTo: string | null
  sections: ActSection[]
  note: string
}

/** Акт сверки: из чего сложился долг, а не только «сколько должен». */
export const getAct = (
  companyId: string, counterpartyId: string, period?: PeriodOpts,
) =>
  get<ActData>(`/api/books/act?company_id=${companyId}`
    + `&counterparty_id=${counterpartyId}` + periodQuery(period))

/** Болезни справочника контрагентов: дубли, карточки без ИНН, несведённые документы. */
export interface CpQuality {
  duplicatesByInn: { key: string; cards: { id: string; name: string; kpp: string | null; docs: number; contracts: number }[] }[]
  duplicatesByName: { key: string; cards: { id: string; name: string; inn: string | null; docs: number }[] }[]
  withoutInn: { id: string; name: string; docs: number; amount: number }[]
  /** Документы, не нашедшие карточку: имя из документа и предложенный кандидат. */
  unlinkedDocs: {
    name: string; inn: string | null; docs: number; amount: number
    candidateId: string | null; candidateName: string | null
  }[]
  emptyCards: number
  docsWithName: number
  docsLinked: number
}

export const getCounterpartyQuality = (companyId: string) =>
  get<CpQuality>(`/api/books/counterparty-quality?company_id=${companyId}`)

/** Привязать несведённые документы с таким именем к выбранной карточке. */
export const linkDocsToCounterparty = (
  companyId: string, counterpartyId: string, name: string,
) =>
  post<{ linked: number }>(
    `/api/books/link-docs?company_id=${companyId}&counterparty_id=${counterpartyId}`
    + `&name=${encodeURIComponent(name)}`, {})

export const getCounterpartyStats = (companyId: string) =>
  get<{ rows: CounterpartyStats[] }>(
    `/api/books/counterparties?company_id=${companyId}&limit=1000`)

export const getCounterpartyCard = (companyId: string, counterpartyId: string) =>
  get<CounterpartyCard>(`/api/books/counterparty?company_id=${companyId}`
    + `&counterparty_id=${counterpartyId}`)

/**
 * Карточка позиции: по какой цене уходит и приходит, сколько на ней зарабатываем,
 * кто берёт. Ключ — КОД номенклатуры: имя в строке документа пишется как угодно.
 */
export interface NomenclatureCard {
  code: string
  name: string
  unit: string | null
  vatRate: number | null
  /** false — кода нет в справочнике 1С, имя взято из строк документов. */
  inCatalog: boolean
  sale: { docs?: number; qty?: number; amount?: number; first?: string; last?: string }
  purchase: { docs?: number; qty?: number; amount?: number; first?: string; last?: string }
  avgSalePrice: number
  avgBuyPrice: number
  /** Наценка к закупочной цене, %. null — позицию не закупали. */
  markupPct: number | null
  prices: { date: string; kind: string; price: number; qty: number; counterparty: string }[]
  clients: { id: string | null; name: string; qty: number; amount: number; docs: number; last: string }[]
  suppliers: { id: string | null; name: string; qty: number; amount: number; docs: number; last: string }[]
  months: {
    month: string; soldQty: number; soldAmount: number
    boughtQty: number; boughtAmount: number
  }[]
}

export const getNomenclatureCard = (companyId: string, code: string) =>
  get<NomenclatureCard>(`/api/books/nomenclature?company_id=${companyId}`
    + `&code=${encodeURIComponent(code)}`)

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

// ── Карточка документа ──────────────────────────────────────────────────────

export interface DocLine {
  [key: string]: unknown
}

export interface DocCard {
  id: string
  type: string
  label: string
  section: string | null
  number: string
  date: string
  counterparty: string | null
  inn: string | null
  counterpartyId: string | null
  contract: { number: string; date: string; type: string | null } | null
  organization: string | null
  amount: number
  vat: number
  operation: string | null
  status: string
  periodStatus: string
  externalId: string
  warehouse: string | null
  /** Входящий документ поставщика: № и дата ЕГО накладной, а не нашей. */
  externalNumber: string | null
  externalDate: string | null
  /** Реквизиты, обязательные для вида: счёт организации, статья ДДС, основание, период. */
  details: Record<string, string>
  /** Строки как приехали из 1С: набор полей у видов разный. */
  lines: DocLine[]
  payments: { date: string | null; title: string | null; amount: number; vat: number }[]
  paid: number
  entries: { date: string | null; accountDt: string | null; accountKt: string | null; amount: number; content: string | null }[]
}

export const getDocCard = (companyId: string, docId: string) =>
  get<DocCard>(`/api/books/doc?company_id=${companyId}&doc_id=${docId}`)
