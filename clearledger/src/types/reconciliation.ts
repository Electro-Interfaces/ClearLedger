/**
 * Типы для сверки данных между источниками.
 */

// ─── Статусы ────────────────────────────────────────

export type ReconciliationTransactionStatus =
  | 'matched'        // Все источники совпали
  | 'msto_wait_done' // MSTO=WAIT, но TF отпущено
  | 'only_msto'      // Только в MSTO (заказ не отпущен)
  | 'only_tf'        // Только в TF (ручной отпуск)
  | 'only_shift'     // Только в смене
  | 'mismatch'       // Расхождение суммы/объёма

export type ReconciliationStatus = 'ok' | 'error'

// ─── Параметры ──────────────────────────────────────

export interface ReconciliationParams {
  dateFrom: string
  dateTo: string
  stationCodes: number[]
  allStations: boolean
  allShifts: boolean
  systemCode: number
}

// ─── Строка результата (транзакция) ─────────────────

export interface ReconciliationTransaction {
  id: string
  date: string
  stationId: number
  stationName: string
  fuelType: string
  aggregatorName: string
  shiftNumber: number | null

  // MSTO
  mstoSum: number | null
  mstoVolume: number | null
  mstoTransactionId?: number
  mstoOperationResult?: string

  // TF (операции отпуска)
  tfSum: number | null
  tfVolume: number | null
  tfTransactionId?: number

  // Смена
  shiftSum: number | null
  shiftVolume: number | null

  status: ReconciliationTransactionStatus
}

// ─── Агрегации ──────────────────────────────────────

export interface ReconciliationByAggregator {
  aggregatorName: string
  mstoSum: number
  mstoVolume: number
  mstoCount: number
  tfSum: number
  tfVolume: number
  tfCount: number
  sumDiff: number
  volumeDiff: number
  status: ReconciliationStatus
}

export interface ReconciliationByFuel {
  fuelName: string
  mstoSum: number
  mstoVolume: number
  tfSum: number
  tfVolume: number
  shiftSum: number
  shiftVolume: number
  status: ReconciliationStatus
}

export interface ReconciliationByShift {
  shiftNumber: number
  shiftDate: string
  openedAt: string
  closedAt: string | null
  mstoSum: number
  mstoVolume: number
  tfSum: number
  tfVolume: number
  shiftSbpRevenue: number
  shiftNonCashVolume: number
  byAggregator: ReconciliationByAggregator[]
  byFuel: ReconciliationByFuel[]
  status: ReconciliationStatus
}

export interface ReconciliationByStation {
  stationId: number
  stationName: string
  byShift: ReconciliationByShift[]
  mstoSum: number
  mstoVolume: number
  tfSum: number
  tfVolume: number
  shiftSbpRevenue: number
  status: ReconciliationStatus
}

// ─── Итоговый результат ─────────────────────────────

export interface ReconciliationSummary {
  totalMstoSum: number
  totalMstoVolume: number
  totalMstoCount: number
  totalTfSum: number
  totalTfVolume: number
  totalTfCount: number
  totalShiftSbpRevenue: number
  totalShiftNonCashVolume: number

  mstoVsTfSumDiff: number
  mstoVsTfVolumeDiff: number
  tfVsShiftSumDiff: number
  tfVsShiftVolumeDiff: number

  matched: number
  mstoWaitDone: number
  onlyMsto: number
  onlyTf: number
  onlyShift: number
  mismatch: number

  hasErrors: boolean
}

export interface ReconciliationResult {
  params: ReconciliationParams
  summary: ReconciliationSummary
  byStation: ReconciliationByStation[]
  byAggregator: ReconciliationByAggregator[]
  transactions: ReconciliationTransaction[]
  executedAt: string
  duration: number
}

// ─── Константы ──────────────────────────────────────

export const TIME_TOLERANCE_MS = 30 * 60 * 1000  // ±30 минут
export const VOLUME_TOLERANCE = 1                  // ±1 литр
export const SUM_TOLERANCE = 10                    // ±10 руб
export const UI_SUM_TOLERANCE = 50                 // для UI статуса
export const UI_VOLUME_TOLERANCE = 1               // для UI статуса

export const STATUS_COLORS: Record<ReconciliationTransactionStatus, string> = {
  matched: 'text-emerald-500',
  msto_wait_done: 'text-amber-500',
  only_msto: 'text-cyan-500',
  only_tf: 'text-blue-500',
  only_shift: 'text-purple-500',
  mismatch: 'text-red-500',
}

export const STATUS_LABELS: Record<ReconciliationTransactionStatus, string> = {
  matched: 'Совпадает',
  msto_wait_done: 'MSTO ожидание',
  only_msto: 'Только MSTO',
  only_tf: 'Только TF',
  only_shift: 'Только смена',
  mismatch: 'Расхождение',
}
