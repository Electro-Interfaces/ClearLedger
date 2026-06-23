/**
 * Платёжная дисциплина по станции × роль (реестр «Договоры и оплаты ЭЗС», energy/РусГидро).
 * L2-слой: статус оплаты энергоснабжения/аренды по каждой ЭЗС.
 * Бэкенд: StationContractSettlement + /references/settlements + /payment-discipline/summary.
 */

export type SettlementRole = 'energy' | 'rent'
export type PaymentStatus = 'paid' | 'unpaid' | 'unknown' | 'special'

export interface StationSettlement {
  id: string
  companyId: string
  locationId: string
  role: SettlementRole
  contractId: string | null
  counterpartyId: string | null
  paidThrough: string | null        // ISO 'YYYY-MM-01' — оплачено по
  paymentStatus: PaymentStatus
  basis: string | null              // договор | разрешение | постановление | приказ | сервитут
  comment: string | null
  period: string | null
  createdAt: string
  updatedAt: string
}

export interface SettlementDetail {
  locationId: string
  stationCode: string | null
  stationName: string | null
  buNumber: string | null
  role: SettlementRole
  counterpartyName: string | null
  contractNumber: string | null
  basis: string | null
  paidThrough: string | null
  paymentStatus: PaymentStatus
  comment: string | null
}

export interface RoleDiscipline {
  role: string
  total: number
  paid: number
  unpaid: number
  unknown: number
  special: number
  withProblem: number
}

export interface PaymentDisciplineSummary {
  stationsCovered: number
  byRole: RoleDiscipline[]
  stationsNoEnergy: number
  stationsNoRent: number
  counterpartiesUnpaidEnergy: number
  counterpartiesUnpaidRent: number
  l1Raw: number
  l2Clean: number
  settlements: number
}

// ── UI-помощники ──────────────────────────────────────────────────────────

export const ROLE_LABEL: Record<SettlementRole, string> = {
  energy: 'Энергоснабжение',
  rent: 'Аренда',
}

export const PAYMENT_META: Record<PaymentStatus, { label: string; cls: string }> = {
  paid:    { label: 'оплачено', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  unpaid:  { label: 'не оплачено', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  unknown: { label: 'нет данных', cls: 'bg-muted text-muted-foreground' },
  special: { label: 'особый порядок', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
}

/** Бейдж «оплачено по <месяц>» из ISO-даты, либо статусная подпись. */
export function paidThroughLabel(s: Pick<StationSettlement, 'paymentStatus' | 'paidThrough'>): string {
  if (s.paymentStatus === 'paid' && s.paidThrough) {
    const m = s.paidThrough.slice(0, 7) // YYYY-MM
    const [y, mo] = m.split('-')
    const months = ['', 'янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    return `оплачено по ${months[Number(mo)] || mo} ${y}`
  }
  return PAYMENT_META[s.paymentStatus]?.label ?? s.paymentStatus
}

/** Сводный статус станции для индикатора в списке/карте: критично если есть unpaid/special-с-проблемой. */
export type StationFlag = 'ok' | 'attention' | 'unpaid' | 'none'

export function stationFlag(settlements: StationSettlement[]): StationFlag {
  if (!settlements.length) return 'none'
  if (settlements.some((s) => s.paymentStatus === 'unpaid')) return 'unpaid'
  if (settlements.some((s) => s.comment || s.paymentStatus === 'special' || s.paymentStatus === 'unknown')) return 'attention'
  return 'ok'
}
