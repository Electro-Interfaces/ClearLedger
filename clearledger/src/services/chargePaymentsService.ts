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

interface P { companyId: string; dateFrom: string; dateTo: string }
const qp = (p: P) => ({ company_id: p.companyId, date_from: p.dateFrom, date_to: p.dateTo })

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
}
export interface ReconSummary {
  period: { from: string; to: string }
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
