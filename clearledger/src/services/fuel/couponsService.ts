/**
 * Журнал купонов (сдача топливом) — читается из STS через Ядро.
 *
 * Купон здесь не хранится: непогашенный остаток это живое обязательство перед
 * клиентом, оно меняется при каждом наливе, и копия показывала бы вчерашний долг.
 */
import { get } from '@/services/apiClient'

export interface CouponRow {
  number: string
  /** Когда выдан. */
  dt: string | null
  /** Когда отоварен — из наливов Ledger (STS этого поля не отдаёт). */
  redeemed_at: string | null
  station_code: number | null
  station_name: string
  pos: number | null
  shift: number | null
  opernum: number | null
  fuel_code: number | null
  fuel_name: string | null
  price: number
  qty_total: number
  qty_used: number
  rest_qty: number
  summ_total: number
  summ_used: number
  rest_summ: number
  /** 0 — активный, 2 — погашен (состояния STS). */
  state_id: number | null
  state_name: string
  type_name: string | null
  author: string | null
  comment: string | null
}

export interface CouponsStats {
  issued: number
  issued_liters: number
  used: number
  used_liters: number
  active: number
  active_liters: number
  active_amount: number
  /** Активные старше `stale_days` — за сдачей, скорее всего, уже не вернутся. */
  stale: number
  stale_days: number
}

export interface CouponsResponse {
  coupons: CouponRow[]
  stats: CouponsStats | Record<string, never>
  warning?: string | null
}

export const getCoupons = (dateFrom: string, dateTo: string, stationCode?: number) =>
  get<CouponsResponse>('/api/fuel/coupons', {
    date_from: dateFrom, date_to: dateTo, station_code: stationCode,
  })
