/**
 * Клиент API /api/charge-sessions/payments/* — эквайринг ЭЗС (витрина АСУиМ).
 *
 * Выручка = `amount` (фактическое списание). `hold` — предавторизация, её нельзя
 * складывать с выручкой: оплата картой трёхтактная (холд → списание → возврат
 * остатка), по холдам сумма получается втрое больше реальной.
 */
import { get } from './apiClient'

export interface PaymentTotals {
  count: number
  amount: number        // списано — это и есть выручка
  hold: number          // заблокировано на карте
  refund: number        // возвращено (остаток холда)
  receipts: number      // платежей с фискальным чеком
  avgCheck: number
  linked: number        // нашли свою сессию
  orphans: number       // сессии в Учёте нет (её ещё не загрузили)
  stuckCount: number    // холд без списания и без возврата
  stuckAmount: number
  scoped: boolean       // ответ сужен контуром — платежи без сессии сюда не вошли
}
export interface PaymentMonth {
  bucket: string; count: number; amount: number; refund: number; receipts: number
}
export interface PaymentType { name: string; count: number; amount: number }
export interface PaymentsSummary {
  totals: PaymentTotals
  byMonth: PaymentMonth[]
  byType: PaymentType[]
}
export interface PaymentLine {
  id: string
  sessionId: string | null
  bankTxnId: string | null
  paidAt: string | null
  amount: number
  hold: number
  refund: number
  opType: string | null
  status: number | null
  receiptUrl: string | null
  phone: string | null
}

interface P {
  companyId: string; dateFrom: string; dateTo: string
  /** Контур рабочей области: коды станций и регионы. Платёж относится к станции
   *  только через свою сессию — платежи без сессии в сужённый ответ не попадают. */
  stations?: string[]; regions?: string[]
}
const qp = (p: P) => ({
  company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo,
  ...(p.stations?.length ? { stations: p.stations.join(',') } : {}),
  ...(p.regions?.length ? { regions: p.regions.join(',') } : {}),
})

export async function getPaymentsSummary(p: P): Promise<PaymentsSummary> {
  return get<PaymentsSummary>('/api/charge-sessions/payments/summary', qp(p))
}

export async function getPaymentsList(
  p: P & { only?: 'orphans' | 'stuck' | 'refunds'; limit?: number },
): Promise<PaymentLine[]> {
  return get<PaymentLine[]>('/api/charge-sessions/payments/list', {
    ...qp(p), ...(p.only ? { only: p.only } : {}), limit: String(p.limit ?? 200),
  })
}

/* ── Отбракованное источником ──────────────────────────────────────────────── */

/**
 * Зарядки, помеченные витриной как недостоверные. В учёте их нет вовсе — ни в
 * сессиях, ни в платежах, — поэтому и в выручке они не участвуют. Экран отвечает
 * на другой вопрос: где и у кого источник счёл транзакцию битой.
 */
export interface RejectedTotals {
  sessions: number
  payments: number
  kwh: number
  amount: number        // деньги отбракованных зарядок
  paid: number          // сколько по ним прошло платежами
  stations: number
  users: number
}
export interface RejectedRow {
  id: string
  sessionId: string
  occurredAt: string | null
  stationCode: string | null
  userId: string | null
  energyKwh: number
  amount: number
  status: string | null
  reason: string
  paidAmount: number | null
}
export interface RejectedSummary {
  totals: RejectedTotals
  byMonth: { bucket: string; count: number; amount: number }[]
  byStation: { code: string; count: number; amount: number }[]
  items: RejectedRow[]
}

export async function getRejected(p: P & { limit?: number }): Promise<RejectedSummary> {
  return get<RejectedSummary>('/api/charge-sessions/rejected', {
    ...qp(p), ...(p.limit ? { limit: String(p.limit) } : {}),
  })
}

/* ── Реализация одной точки (вкладка «Реализация» карточки объекта) ────────── */

export interface StationSalesTotals {
  sessions: number
  kwh: number
  amount: number          // сумма по сессиям (сколько отпущено на деньги)
  avgCheck: number
  clients: number
  firstAt: string | null
  lastAt: string | null
  payments: number
  paid: number            // фактически списано эквайрингом
  hold: number
  refund: number
  receipts: number        // платежей с фискальным чеком
  unpaidSessions: number  // сессия с суммой есть, платежа к ней нет
}
export interface StationSalesMonth {
  bucket: string; sessions: number; kwh: number; amount: number
  payments: number; paid: number; receipts: number
}
export interface StationSales {
  totals: StationSalesTotals
  byMonth: StationSalesMonth[]
}

export async function getStationSales(
  companyId: string, locationId: string, months = 12,
): Promise<StationSales> {
  return get<StationSales>('/api/charge-sessions/station-sales', {
    company_id: companyId, location_id: locationId, months: String(months),
  })
}

/* ── Отпуск энергии одной станцией за период (вкладка «Энергия») ───────────── */

export interface StationEnergy {
  /** Шаг ряда: период до 62 дней разбивается по дням, дальше — по месяцам. */
  bucket: 'day' | 'month'
  totals: {
    sessions: number
    charged: number        // из них дали ток (energy_kwh > 0)
    kwh: number
    avgKwh: number         // среднее по СОСТОЯВШИМСЯ заправкам (канон раздела)
    avgMin: number
    clients: number
    visits: number
    visitsCharged: number  // визиты, закончившиеся зарядкой
    avgMonthKwh: number    // среднемесячный отпуск за период (с учётом простоя)
    months: number
    lastAt: string | null
  }
  series: { bucket: string; sessions: number; charged: number; kwh: number }[]
  byConnector: { no: string; type: string; sessions: number; kwh: number }[]
}

export async function getStationEnergy(
  companyId: string, locationId: string, from: string, to: string,
): Promise<StationEnergy> {
  return get<StationEnergy>('/api/charge-sessions/station-energy', {
    company_id: companyId, location_id: locationId, date_from: from, date_to: to,
  })
}

/* ── Сверка «сессия ↔ платёж ↔ чек» ───────────────────────────────────────── */

export interface ReconKind {
  key: 'impossible' | 'double' | 'underpaid' | 'overpaid' | 'no_payment' | 'no_receipt'
    | 'orphan' | 'refund_full' | 'hold_rule' | 'receipt_no_txn' | 'not_card'
  label: string
  hint: string
  count: number
  amount: number   // начислено по сессиям
  paid: number     // списано банком
  gap: number      // деньги, о которых спор
  /** Вид, который контуром не сужается (платёж без сессии не привязан к станции). */
  unscopable?: boolean
}
export interface ReconSummary {
  period: { from: string; to: string }
  /** Ответ сужен контуром рабочей области: платежи без сессии в него не входят. */
  scoped?: boolean
  totals: {
    sessions: number; amount: number; paid: number; energy_kwh: number; gap: number
    /** кВт·ч из сессий, противоречащих физике: ровно на них завышен отпуск. */
    bad_energy_kwh: number
    /** Начислено рознице — единственное, что сопоставимо со списаниями банка. */
    retail_amount: number
    /** Корпоратив: постоплата по договору, в сверку эквайринга не входит. */
    corp_amount: number
  }
  kinds: ReconKind[]
}
export interface ReconRow {
  id: string
  session: string | null
  station: string | null
  at: string | null
  energy: number
  amount: number
  paid: number
  gap: number
  receipt: boolean
  payments: number
  powerKw: number | null
  /** Холд и возврат — только у платёжных расхождений, у сессионных null. */
  hold: number | null
  refund: number | null
}

export async function getReconciliation(p: P): Promise<ReconSummary> {
  return get<ReconSummary>('/api/charge-sessions/reconciliation', qp(p))
}
export async function getReconciliationRows(
  p: P & { kind: string; limit?: number },
): Promise<ReconRow[]> {
  return get<ReconRow[]>('/api/charge-sessions/reconciliation/list', {
    ...qp(p), kind: p.kind, limit: String(p.limit ?? 200),
  })
}

/** Где копятся расхождения: разрез сверки по станции или региону. */
export interface ReconByRow {
  label: string
  /** Код станции — им строки соединяются с разрезами «Продаж» (там подпись «Имя (код)»). */
  code?: string | null
  sessions: number
  amount: number
  paid: number
  /** Розница и корпоратив отдельно: сверять с эквайрингом можно только первое. */
  retailAmount: number
  corpAmount: number
  gap: number
  gapPct: number
  impossible: number
  impossibleAmount: number
  /** Отпуск и та его часть, что пришла из недостоверных строк. */
  energy: number
  impossibleEnergy: number
  impossibleEnergyPct: number
  underpaid: number
  multi: number
  noReceipt: number
  /** В скольких месяцах периода были расхождения (и сколько месяцев станция работала). */
  badMonths: number
  months: number
  /** Хроника: расхождения повторяются больше чем в одном месяце — это оборудование. */
  chronic: boolean
}
export type ReconDim = 'station' | 'region' | 'month' | 'connector' | 'charge_type'
  | 'client' | 'card_status'

export async function getReconciliationBy(
  p: P & { by: ReconDim; limit?: number },
): Promise<ReconByRow[]> {
  return get<ReconByRow[]>('/api/charge-sessions/reconciliation/by', {
    ...qp(p), by: p.by, limit: String(p.limit ?? 100),
  })
}
