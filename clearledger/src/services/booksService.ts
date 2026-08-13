/**
 * Клиент `/api/books/*` — бухгалтерия-эталон офисного пространства и её разрезы.
 *
 * Числа считает бэкенд по регистру (`gl_entries`) и документам (`accounting_docs`):
 * фронт ничего не пересчитывает, иначе «Продажи» и «Бухгалтерия» разошлись бы в
 * выручке на копейки округления — а именно сходимость с бухгалтерией здесь и есть
 * смысл продукта.
 */
import { get, patch, post } from './apiClient'

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

/** Связные выводы: что показатели означают вместе, а не по отдельности. */
export interface Insights {
  insights: {
    key: string
    tone: 'danger' | 'warn' | 'good'
    title: string
    /** Вывод словами. */
    text: string
    /** Цифры, из которых он получен — чтобы вывод можно было проверить. */
    facts: string[]
    mode: string
    sub: string
    /** К чему этот вывод ведёт: связь задана правилом, а не корреляцией. */
    leadsTo: { key: string; why: string }[]
  }[]
  count: number
  /** Главная мысль: с чего начинается разговор о компании. */
  headline: string | null
}

export const getInsights = (companyId: string) =>
  get<Insights>(`/api/books/insights?company_id=${companyId}`)

/* ── «Экономика»: результат, расходы, налоги ─────────────────────────────── */

export interface PnlTotals {
  revenue: number; vat: number; excise: number; net: number
  /** Себестоимость товара и та её часть, у которой источник не опознан. */
  cogs: number; cogsOther: number; cogsTotal: number
  gross: number
  commercial: number; admin: number; operating: number
  otherIncome: number; otherExpense: number; interest: number
  beforeTax: number; tax: number; profit: number
  grossPct: number | null; operatingPct: number | null; profitPct: number | null
}

export interface PnlData {
  months: (PnlTotals & { month: string })[]
  totals: PnlTotals
  years: (PnlTotals & { year: string })[]
  /** Что бухгалтерия закрыла на 84 счёт — эталон рядом с расчётом. */
  closedToRetained: number
  /** Проводок по счёту 90: ноль значит «план счетов другой», а не «продаж не было». */
  salesEntries: number
  /** Управленческие расходы закрываются через себестоимость (директ-костинг выключен). */
  adminInCogs: boolean
}

export const getPnl = (companyId: string, period?: PeriodOpts) =>
  get<PnlData>(`/api/books/pnl?company_id=${companyId}` + periodQuery(period))

/** Проводки, из которых сложилась строка отчёта о результате. */
export interface PnlEntries {
  line: string
  label: string
  rows: {
    date: string | null; accountDt: string | null; accountKt: string | null
    amount: number; docKind: string | null; docTitle: string | null; content: string | null
  }[]
  total: number
  count: number
  shown: number
}

export const getPnlEntries = (
  companyId: string, line: string, period?: PeriodOpts,
) =>
  get<PnlEntries>(`/api/books/pnl-entries?company_id=${companyId}&line=${line}`
    + periodQuery(period))

/** Мост «затраты → отчёт»: начислено на счетах учёта против списанного в результат. */
export interface CostBridge {
  rows: {
    account: string; name: string | null
    accrued: number; written: number; moved: number; rest: number
  }[]
  accrued: number
  written: number
  rest: number
  inPnl: number
}

export const getCostBridge = (companyId: string, period?: PeriodOpts) =>
  get<CostBridge>(`/api/books/cost-bridge?company_id=${companyId}` + periodQuery(period))

export interface ExpensesData {
  accounts: {
    account: string; name: string | null; amount: number
    sources: { source: string; sourceName: string | null; amount: number; entries: number }[]
  }[]
  rows: {
    account: string; accountName: string | null
    source: string; sourceName: string | null; amount: number; entries: number
  }[]
  months: { month: string; amount: number }[]
  /** Статьи затрат из субконто оборотов — то, за что платим, а не кому. */
  items: { item: string; account: string; amount: number; months: number }[]
  total: number
  itemsTotal: number
}

export const getExpenses = (companyId: string, period?: PeriodOpts) =>
  get<ExpensesData>(`/api/books/expenses?company_id=${companyId}` + periodQuery(period))

export interface TaxesData {
  rows: { account: string; name: string; accrued: number; entries: number }[]
  months: { month: string; accrued: number; paid: number }[]
  accrued: number
  paid: number
  revenueNet: number
  /** Нагрузка от УПЛАЧЕННОГО — так её считает и налоговая служба. */
  loadPct: number | null
  /** Раскладка по смыслу: что строка отчёта, что транзит, что удержание. */
  groups: { profitTax: number; vat: number; ndfl: number; contributions: number }
  /** Эффективная ставка — только при положительной прибыли до налога. */
  etrPct: number | null
}

export const getTaxes = (companyId: string, period?: PeriodOpts) =>
  get<TaxesData>(`/api/books/taxes?company_id=${companyId}` + periodQuery(period))

/** Сигналы продукта: что сейчас не так и куда идти разбираться. */
export interface Attention {
  signals: {
    key: string; level: 'danger' | 'warn' | 'info'
    title: string; value: string; why: string
    /** Куда ведёт сигнал: раздел рельсы и пункт второй панели. */
    mode: string; sub: string
    count: number | null
  }[]
  danger: number
  warn: number
  asOf: string
}

export const getAttention = (companyId: string, period?: PeriodOpts) =>
  get<Attention>(`/api/books/attention?company_id=${companyId}` + periodQuery(period))

/** Реестр старения долга: сколько, чьё и сколько дней. */
export interface ArAging {
  buckets: {
    key: string; label: string; count: number; amount: number
    /** Ожидаемая доля невозврата по возрасту, % — ставка экспертная. */
    riskPct: number; risk: number
  }[]
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
  /** Ожидаемые потери по долгу: сумма бакетов, взвешенных ставкой риска. */
  risk: number
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

/** Прогноз поступлений от открытого долга по исторической кривой инкассации. */
export interface CashForecast {
  rows: {
    id: string; number: string; date: string; counterparty: string
    counterpartyId: string | null; amount: number; paid: number
    rest: number; age: number
    expected: number; expectedPct: number; in30: number; in90: number
  }[]
  openAmount: number
  openCount: number
  expected: number
  windows: { days: number; label: string; amount: number }[]
  curve: { days: number; pct: number }[]
  totalSharePct: number
  historyInvoices: number
  historyBilled: number
  unknownCount: number
  unknownAmount: number
  asOf: string
}

export const getCashForecast = (companyId: string) =>
  get<CashForecast>(`/api/books/cash-forecast?company_id=${companyId}`)

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
    /** Корзина срока — считает сервер, пороги там же. */
    bucket: string
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

/** Движение денег по статьям: за что платили и от кого получали. */
export interface CashflowItems {
  rows: {
    item: string; kind: string
    inflow: number; outflow: number; net: number
    inDocs: number; outDocs: number
    first: string | null; last: string | null
  }[]
  months: { month: string; inflow: number; outflow: number }[]
  kinds: {
    kind: string; label: string
    inflow: number; outflow: number; net: number; items: number
  }[]
  inflow: number
  outflow: number
  /** Документы без статьи: пока их много, разрез неполон. */
  noItemDocs: number
  noItemAmount: number
}

export const getCashflowItems = (companyId: string, period?: PeriodOpts) =>
  get<CashflowItems>(`/api/books/cashflow-items?company_id=${companyId}` + periodQuery(period))

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

// ── Расчёт с персоналом ─────────────────────────────────────────────────────
// ⚠ ПДн: ответ содержит ФИО, ИНН и СНИЛС сотрудников клиента.

export interface PayrollData {
  /** Регистры НДФЛ и взносов: из них собираются 6-НДФЛ и РСВ. */
  taxRegisters: { period: string; income: number; ndflAccrued: number
    ndflPaid: number; contribBase: number; contribAccrued: number }[]
  totals: {
    accrued: number
    ndfl: number
    contributions: number
    paid: number
    employees: number
    /** Долг перед сотрудниками — сальдо 70, а не «начислено минус выплачено». */
    debt: number
    /** Аванс за первую половину месяца: входит в начисления, но проводок не делает. */
    advance: number
  }
  months: { month: string; accrued: number; ndfl: number; contributions: number; paid: number }[]
  employees: {
    id: string | null; name: string; inn: string | null; snils: string | null
    accrued: number; ndfl: number; paid: number; contributions: number; months: number
  }[]
  kinds: { kind: string; name: string; amount: number; rows: number }[]
  docs: {
    id: string; type: string; label: string; number: string; date: string
    amount: number; status: string; advance: boolean; month: string | null
  }[]
}

export const getPayroll = (companyId: string) =>
  get<PayrollData>(`/api/books/payroll?company_id=${companyId}`)

// ── Закрытие периода ────────────────────────────────────────────────────────

export interface ClosingData {
  period: string | null
  months: {
    month: string; status: string; docs: number; amount: number
    entries: number; turnover: number
    closedAt: string | null; closureSource: string | null
  }[]
  /** Находки: чего не хватает, чтобы закрывать месяц спокойно. */
  gaps: {
    key: string; title: string; why: string; count: number; amount: number
    rows: { id: string; date: string; number: string; counterparty: string; amount: number; period: string }[]
  }[]
  /** Тот же список, свёрнутый по контрагенту: документы просят у людей. */
  byCounterparty: { counterparty: string; count: number; amount: number; kinds: string[] }[]
  /** Можно ли дооформить недостающее задним числом: зависит от способа получения. */
  docFlow: { lock: string | null; edoDocs: number; note: string }
}

export const getClosing = (companyId: string, period?: string | null) =>
  get<ClosingData>(`/api/books/closing?company_id=${companyId}`
    + (period ? `&period=${period}` : ''))

// ── Проверки учёта ──────────────────────────────────────────────────────────
// Не о загрузке (это `/quality`), а о самом учёте: что в нём не так.

export interface CheckItem {
  key: string
  group: string
  title: string
  /** Чем грозит — показывается только у сработавших проверок. */
  risk: string
  status: 'ok' | 'warn' | 'error' | 'info' | 'reviewed'
  count: number
  amount: number
  /** Отметка «разобрано» на всей проверке. */
  decision?: FindingDecision | null
  value: string
  rows: { id: string; date: string; number: string; subject: string; amount: number }[]
}

export interface ChecksData {
  groups: { key: string; title: string; checks: CheckItem[]
    errors: number; warnings: number; reviewed: number }[]
  /** Настройки, с которыми сверяется учёт: учётная политика и налоговый режим. */
  policy: { kind: string; title: string; settings: Record<string, string> }[]
  errors: number
  warnings: number
  reviewed: number
  ok: number
}

export const getChecks = (companyId: string) =>
  get<ChecksData>(`/api/books/checks?company_id=${companyId}`)

// ── Требования документов ───────────────────────────────────────────────────
// Находка, взятая под контроль: срок, ответственный, лента обращений, итог.

export interface DocRequestItem {
  id: string
  period: string
  rule: string
  counterparty: string
  counterpartyId: string | null
  docKind: string
  amount: number
  status: string
  statusLabel: string
  channel: string | null
  dueDate: string | null
  assignee: string | null
  contact: string | null
  note: string | null
  escalations: { at: string; who: string; channel: string; text: string }[]
  /** Просрочка — состояние срока, а не статус: статус говорит, что сделали. */
  overdue: boolean
  sourceDocId: string | null
  resolvedAt: string | null
}

export interface RequestsData {
  items: DocRequestItem[]
  total: number
  open: number
  overdue: number
  amount: number
  byStatus: { status: string; label: string; count: number }[]
}

export const getRequests = (companyId: string, opts: { period?: string; status?: string } = {}) =>
  get<RequestsData>(`/api/books/requests?company_id=${companyId}`
    + (opts.period ? `&period=${opts.period}` : '')
    + (opts.status ? `&status=${opts.status}` : ''))

/** Поставить находки правила на контроль. Повторный вызов дублей не заводит. */
export const createRequestsFromGaps = (
  companyId: string, rule: string, period?: string | null,
) => post<{ created: number; skipped: number; title: string; dueDate: string }>(
  `/api/books/requests/from-gaps?company_id=${companyId}&rule=${rule}`
  + (period ? `&period=${period}` : ''), {})

export const updateRequest = (
  companyId: string, id: string,
  v: { status?: string; escalation?: string; dueDate?: string; assignee?: string },
) => patch<{ id: string; status: string; statusLabel: string }>(
  `/api/books/requests/${id}?company_id=${companyId}`
  + (v.status ? `&status=${v.status}` : '')
  + (v.escalation ? `&escalation=${encodeURIComponent(v.escalation)}` : '')
  + (v.dueDate ? `&due_date=${v.dueDate}` : '')
  + (v.assignee ? `&assignee=${encodeURIComponent(v.assignee)}` : ''), {})

/** Закрыть требования, по которым документ уже появился в слое. */
export const resolveRequests = (companyId: string) =>
  post<{ checked: number; resolved: number }>(
    `/api/books/requests/resolve?company_id=${companyId}`, {})

// ── Налоги заранее ──────────────────────────────────────────────────────────
// Не факт (это `getTaxes` — начислено и уплачено), а ПРОГНОЗ: сколько заплатим,
// если закрыть период как есть, и сколько станет, когда документы соберут.

export interface TaxForecastQuarter {
  quarter: string
  vatOut: number; vatIn: number; vatDue: number
  income: number; expense: number; profit: number; profitTax: number
  docsIssued: number; docsReceived: number
  /** Что даст сбор документов, взятых под контроль в «Требованиях». */
  pendingVat: number; pendingExpense: number
  vatDueIfCollected: number; profitIfCollected: number; profitTaxIfCollected: number
  saving: number
}

export interface TaxForecast {
  quarters: TaxForecastQuarter[]
  totals: {
    vatDue: number; vatDueIfCollected: number
    profitTax: number; profitTaxIfCollected: number
    saving: number; ndfl: number; contributions: number
  }
  budget: { account: string; name: string; debt: number }[]
  disclaimer: string
  /** Чего в расчёте нет: без этого списка оценку примут за декларацию. */
  notIncluded: string[]
  rates: { vat: number; profit: number }
}

export const getTaxForecast = (companyId: string, year?: number) =>
  get<TaxForecast>(`/api/books/tax-forecast?company_id=${companyId}`
    + (year ? `&year=${year}` : ''))

// ── Слой выгрузки ───────────────────────────────────────────────────────────
// Слой — «что есть», выгрузка — «что предлагаем провести». Корректировка лежит
// рядом с документом и не трогает исходник.

export interface ExportAdjustmentItem {
  id: string
  period: string
  field: string
  fieldLabel: string
  oldValue: string | null
  newValue: string | null
  reason: string
  status: string
  statusLabel: string
  createdBy: string | null
  approvedBy: string | null
  ruleId: string | null
  doc: {
    id: string; type: string; label: string; number: string; date: string
    counterparty: string; amount: number; vat: number
  } | null
}

export interface ExportLayerData {
  period: string | null
  adjustments: ExportAdjustmentItem[]
  rules: {
    id: string; name: string; docType: string | null; docTypeLabel: string
    matchText: string | null; field: string; fieldLabel: string; newValue: string
    reason: string; active: boolean; validFrom: string | null; applied: number
  }[]
  byStatus: { status: string; label: string; count: number }[]
  /** Что изменится в выгрузке против слоя — по утверждённым корректировкам. */
  effect: { amount: number; vat: number; profitTax: number; docs: number }
}

export const getExportLayer = (companyId: string, period?: string) =>
  get<ExportLayerData>(`/api/books/export-layer?company_id=${companyId}`
    + (period ? `&period=${period}` : ''))

export const createAdjustment = (
  companyId: string, docId: string, field: string, newValue: string, reason: string,
) => post<{ id: string; status: string }>(
  `/api/books/export-layer/adjustments?company_id=${companyId}&doc_id=${docId}`
  + `&field=${field}&new_value=${encodeURIComponent(newValue)}`
  + `&reason=${encodeURIComponent(reason)}`, {})

export const updateAdjustment = (
  companyId: string, id: string, v: { status?: string; newValue?: string; reason?: string },
) => patch<{ id: string; status: string; statusLabel: string }>(
  `/api/books/export-layer/adjustments/${id}?company_id=${companyId}`
  + (v.status ? `&status=${v.status}` : '')
  + (v.newValue ? `&new_value=${encodeURIComponent(v.newValue)}` : '')
  + (v.reason ? `&reason=${encodeURIComponent(v.reason)}` : ''), {})

export const applyExportRules = (companyId: string, period: string) =>
  post<{ created: number; rules: number; period: string }>(
    `/api/books/export-layer/apply-rules?company_id=${companyId}&period=${period}`, {})

/** Помесячная динамика и находки-поводы: правило не нарушено, но цифра выделяется. */
export interface TrendsData {
  months: { month: string; revenue: number; cost: number; expense: number
    profit: number; docs: number }[]
  findings: { key: string; title: string; why: string; count: number; open: number
    decision: FindingDecision | null
    rows: { period: string; subject: string; amount: number; note: string
      rowKey: string; decision: FindingDecision | null }[] }[]
  /** Показатели, которые инспекция считает по той же отчётности (приказ ММ-3-06/333@). */
  fnsRisk: { title: string; value: string; status: string; note: string }[]
  summary: { months: number; findings: number; open: number; kinds: number
    scale: number; thresholds: { big: number; notable: number } }
}

export const getTrends = (companyId: string) =>
  get<TrendsData>(`/api/books/trends?company_id=${companyId}`)

/** Сроки и бюджет: календарь 1С, ЕНС, уведомления и сданная отчётность. */
export interface TaxCalendarData {
  today: string
  note: string
  tasks: { due: string; title: string; period: string | null; rule: string | null
    period_kind: string | null; status: string | null; state: string }[]
  enp: { period: string; title: string; tax: string | null; due: string | null
    amount: number; advance: boolean }[]
  notices: { number: string; date: string; amount: number; taxes: string | null
    due: string | null; lines: unknown[] }[]
  filed: { date: string; title: string; period: string | null; signed: string | null }[]
  debts: { account: string; name: string; amount: number }[]
  /** Долг перед бюджетом на конец каждого месяца — из помесячных срезов сальдо. */
  debtMonths: { month: string; amount: number }[]
  summary: { overdue: number; soon: number; enpBalance: number
    budgetDebt: number; filed: number }
}

export const getTaxCalendar = (companyId: string) =>
  get<TaxCalendarData>(`/api/books/calendar?company_id=${companyId}`)

/** Отметка «разобрано» у находки проверки или тенденции. */
export interface FindingDecision {
  decision: string; note: string; by?: string | null
  at?: string | null; until?: string | null
}

export const decideFinding = (
  companyId: string, scope: 'checks' | 'trends' | 'closing',
  ruleKey: string, v: { rowKey?: string; decision: string; note?: string; until?: string },
) => post<{ decision: string; note?: string; until?: string | null }>(
  `/api/books/findings/decision?company_id=${companyId}&scope=${scope}`
  + `&rule_key=${encodeURIComponent(ruleKey)}`
  + `&row_key=${encodeURIComponent(v.rowKey ?? '')}`
  + `&decision=${v.decision}`
  + (v.note ? `&note=${encodeURIComponent(v.note)}` : '')
  + (v.until ? `&valid_until=${v.until}` : ''), {})

/** Заготовка письма контрагенту по требованию. */
export interface RequestLetter {
  to: string; counterparty: string; subject: string; body: string
  mailbox: { id: string; address: string; title: string } | null
  canSend: boolean; why: string | null
  due: string | null; period: string
  escalations: { at: string; by: string; kind: string; to?: string; subject?: string }[]
}

export const getRequestLetter = (companyId: string, id: string) =>
  get<RequestLetter>(`/api/books/requests/${id}/letter?company_id=${companyId}`)

export const sendRequestLetter = (
  companyId: string, id: string, v: { to: string; subject: string; body: string },
) => post<{ sent: boolean; status: string; escalations: number }>(
  `/api/books/requests/${id}/send?company_id=${companyId}`
  + `&to=${encodeURIComponent(v.to)}&subject=${encodeURIComponent(v.subject)}`
  + `&body=${encodeURIComponent(v.body)}`, {})
