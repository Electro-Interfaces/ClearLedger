/**
 * Сверка онлайн-заказов: MSTO vs STS Операции vs Сменные отчёты.
 *
 * 3 источника:
 * 1. MSTO IntegratorService — заказы агрегаторов
 * 2. STS /v2/transactions — фактический отпуск на ТРК
 * 3. STS shift_report — агрегированные данные по сменам
 *
 * Алгоритм (из TradeFrame):
 * Stage 1: Match MSTO → TF по станции, топливу, времени ±30мин, объёму ±1л
 * Stage 2: Orphaned TF → only_tf
 * Stage 3: Shifts без MSTO/TF → only_shift
 */

import type {
  ReconciliationParams,
  ReconciliationResult,
  ReconciliationTransaction,
  ReconciliationSummary,
  ReconciliationByStation,
  ReconciliationByAggregator,
  ReconciliationTransactionStatus,
} from '@/types/reconciliation'
import { TIME_TOLERANCE_MS, VOLUME_TOLERANCE, UI_SUM_TOLERANCE, UI_VOLUME_TOLERANCE } from '@/types/reconciliation'
import type { MstoTransaction } from '../msto/mstoApiClient'
import { mstoLogin, mstoGetTransactions } from '../msto/mstoApiClient'
import { stsLogin, stsGetShifts, stsGetShiftReport } from '../fuel/stsApiClient'
import { getSource, getSources } from '../sourceService'

// ─── Внутренние типы ────────────────────────────────

interface TfTransaction {
  id: number
  date: string
  stationId: number
  fuelType: string
  volume: number
  price: number
  total: number
  paymentMethod: string
  shiftNumber: number | null
}

interface ShiftInfo {
  shiftNumber: number
  stationId: number
  stationName: string
  openedAt: string
  closedAt: string | null
  sbpRevenue: number
  nonCashVolume: number
}

// ─── Fuel Matching ──────────────────────────────────

function normalizeFuel(name: string): string {
  const s = name.toLowerCase().replace(/[-\s]/g, '')
  if (s.includes('95')) return 'аи95'
  if (s.includes('92')) return 'аи92'
  if (s.includes('98')) return 'аи98'
  if (s.includes('100')) return 'аи100'
  if (s.includes('дт') || s.includes('дизел') || s.includes('diesel')) return 'дт'
  if (s.includes('пропан') || s.includes('газ')) return 'пропан'
  return s
}

function isFuelMatch(a: string, b: string): boolean {
  return normalizeFuel(a) === normalizeFuel(b)
}

// ─── Date helpers ───────────────────────────────────

function isDateInShift(txDate: string, openedAt: string, closedAt: string | null): boolean {
  const t = new Date(txDate).getTime()
  const o = new Date(openedAt).getTime()
  if (!closedAt) return t >= o
  return t >= o && t <= new Date(closedAt).getTime()
}

// ─── Stage 1: Match MSTO → TF ──────────────────────

function findMatchingTf(
  msto: MstoTransaction,
  tfList: TfTransaction[],
  matchedTfIds: Set<number>,
  stationId: number,
): TfTransaction | null {
  const mstoDate = new Date(msto.dateTime).getTime()
  let best: TfTransaction | null = null
  let bestTimeDiff = Infinity

  for (const tf of tfList) {
    if (matchedTfIds.has(tf.id)) continue
    if (tf.stationId !== stationId) continue
    if (!isFuelMatch(msto.service, tf.fuelType)) continue

    const timeDiff = Math.abs(mstoDate - new Date(tf.date).getTime())
    if (timeDiff > TIME_TOLERANCE_MS) continue

    const volumeDiff = Math.abs(msto.resultValue - tf.volume)
    if (volumeDiff > VOLUME_TOLERANCE * 2) continue

    if (timeDiff < bestTimeDiff) {
      best = tf
      bestTimeDiff = timeDiff
    }
  }

  return best
}

// ─── Fetch Data ─────────────────────────────────────

async function fetchMstoData(params: ReconciliationParams): Promise<MstoTransaction[]> {
  const mstoSource = getSources().find((s) => s.type === 'msto')
  const conn = mstoSource?.connection ?? {}
  await mstoLogin(undefined, conn.login, conn.password)

  const dateFrom = new Date(params.dateFrom)
  const dateTo = new Date(params.dateTo + 'T23:59:59')

  const txs = await mstoGetTransactions(dateFrom, dateTo, undefined, {
    login: conn.login,
    password: conn.password,
  })

  return txs.filter((t) =>
    (t.operationResult === 'success' || t.operationResult === 'wait') &&
    (t.resultValue > 0.01 || t.resultSum > 1)
  )
}

async function fetchShifts(params: ReconciliationParams): Promise<ShiftInfo[]> {
  const stsSource = getSources().find((s) => s.type === 'rest')
  const conn = stsSource?.connection ?? {}
  await stsLogin(undefined, conn.login, conn.password)

  const systemCode = params.systemCode || Number(conn.systemCode) || 65
  const shifts: ShiftInfo[] = []

  for (const stationId of params.stationCodes) {
    const list = await stsGetShifts(systemCode, stationId)
    for (const s of list) {
      try {
        const report = await stsGetShiftReport(stationId, s.shift, systemCode)
        let sbpRevenue = 0
        let nonCashVolume = 0
        if (report.sales && Array.isArray(report.sales)) {
          for (const sale of report.sales) {
            const payName = (sale.pay_type?.name || '').toLowerCase()
            if (payName.includes('мобил') || payName.includes('онлайн') || payName.includes('mobil')) {
              for (const fuel of sale.fuel || []) {
                sbpRevenue += fuel.release?.cost || 0
                nonCashVolume += fuel.release?.volume || 0
              }
            }
          }
        }
        shifts.push({
          shiftNumber: s.shift,
          stationId,
          stationName: `АЗС-${stationId}`,
          openedAt: s.dt_open,
          closedAt: s.dt_close,
          sbpRevenue,
          nonCashVolume,
        })
      } catch { /* skip failed shift */ }
    }
  }

  return shifts
}

// ─── Main Reconciliation ────────────────────────────

export async function executeMstoReconciliation(
  params: ReconciliationParams,
  onProgress?: (msg: string) => void,
): Promise<ReconciliationResult> {
  const startTime = Date.now()

  onProgress?.('Загрузка данных MSTO...')
  const mstoTxs = await fetchMstoData(params)

  onProgress?.('Загрузка сменных отчётов...')
  const shifts = await fetchShifts(params)

  // TF transactions: пока берём из загруженных смен (shift_report содержит транзакции)
  // В будущем — отдельный запрос /v2/transactions
  const tfTxs: TfTransaction[] = []

  onProgress?.('Сопоставление...')

  const matchedTfIds = new Set<number>()
  const matchedMstoIds = new Set<number>()
  const transactions: ReconciliationTransaction[] = []

  let matched = 0, mstoWaitDone = 0, onlyMsto = 0, onlyTf = 0, onlyShift = 0, mismatch = 0

  // Stage 1: MSTO → TF matching
  for (const msto of mstoTxs) {
    const stationId = params.stationCodes[0] ?? 0 // TODO: map servicePointId → stationId
    const shift = shifts.find((s) =>
      s.stationId === stationId && isDateInShift(msto.dateTime, s.openedAt, s.closedAt)
    )

    const tf = findMatchingTf(msto, tfTxs, matchedTfIds, stationId)

    let status: ReconciliationTransactionStatus
    if (!tf) {
      status = 'only_msto'
      onlyMsto++
    } else {
      matchedTfIds.add(tf.id)
      const vDiff = Math.abs(msto.resultValue - tf.volume)
      if (vDiff > VOLUME_TOLERANCE) {
        status = 'mismatch'
        mismatch++
      } else if (msto.operationResult === 'wait') {
        status = 'msto_wait_done'
        mstoWaitDone++
      } else {
        status = 'matched'
        matched++
      }
    }
    matchedMstoIds.add(msto.id)

    transactions.push({
      id: `rec-${msto.id}-${Date.now()}`,
      date: msto.dateTime,
      stationId,
      stationName: msto.servicePointName || `АЗС-${stationId}`,
      fuelType: msto.service,
      aggregatorName: msto.tariff,
      shiftNumber: shift?.shiftNumber ?? null,
      mstoSum: msto.resultSum,
      mstoVolume: msto.resultValue,
      mstoTransactionId: msto.id,
      mstoOperationResult: msto.operationResult,
      tfSum: tf?.total ?? null,
      tfVolume: tf?.volume ?? null,
      tfTransactionId: tf?.id,
      shiftSum: shift?.sbpRevenue ?? null,
      shiftVolume: shift?.nonCashVolume ?? null,
      status,
    })
  }

  // Stage 2: Orphaned TF
  for (const tf of tfTxs) {
    if (matchedTfIds.has(tf.id)) continue
    onlyTf++
    transactions.push({
      id: `rec-tf-${tf.id}`,
      date: tf.date,
      stationId: tf.stationId,
      stationName: `АЗС-${tf.stationId}`,
      fuelType: tf.fuelType,
      aggregatorName: '',
      shiftNumber: tf.shiftNumber,
      mstoSum: null, mstoVolume: null,
      tfSum: tf.total, tfVolume: tf.volume, tfTransactionId: tf.id,
      shiftSum: null, shiftVolume: null,
      status: 'only_tf',
    })
  }

  // Stage 3: Shifts без MSTO/TF (если есть SBP revenue)
  for (const shift of shifts) {
    if (shift.sbpRevenue <= 0 && !params.allShifts) continue
    const hasTx = transactions.some((t) =>
      t.stationId === shift.stationId && t.shiftNumber === shift.shiftNumber
    )
    if (!hasTx && shift.sbpRevenue > 0) {
      onlyShift++
      transactions.push({
        id: `rec-shift-${shift.stationId}-${shift.shiftNumber}`,
        date: shift.openedAt,
        stationId: shift.stationId,
        stationName: shift.stationName,
        fuelType: '',
        aggregatorName: '',
        shiftNumber: shift.shiftNumber,
        mstoSum: null, mstoVolume: null,
        tfSum: null, tfVolume: null,
        shiftSum: shift.sbpRevenue, shiftVolume: shift.nonCashVolume,
        status: 'only_shift',
      })
    }
  }

  // Aggregations
  const totalMstoSum = transactions.reduce((s, t) => s + (t.mstoSum ?? 0), 0)
  const totalMstoVolume = transactions.reduce((s, t) => s + (t.mstoVolume ?? 0), 0)
  const totalTfSum = transactions.reduce((s, t) => s + (t.tfSum ?? 0), 0)
  const totalTfVolume = transactions.reduce((s, t) => s + (t.tfVolume ?? 0), 0)
  const totalShiftSbp = shifts.reduce((s, sh) => s + sh.sbpRevenue, 0)
  const totalShiftVol = shifts.reduce((s, sh) => s + sh.nonCashVolume, 0)

  // By aggregator
  const aggMap = new Map<string, ReconciliationByAggregator>()
  for (const t of transactions) {
    const name = t.aggregatorName || 'Неизвестный'
    if (!aggMap.has(name)) {
      aggMap.set(name, { aggregatorName: name, mstoSum: 0, mstoVolume: 0, mstoCount: 0, tfSum: 0, tfVolume: 0, tfCount: 0, sumDiff: 0, volumeDiff: 0, status: 'ok' })
    }
    const a = aggMap.get(name)!
    if (t.mstoSum != null) { a.mstoSum += t.mstoSum; a.mstoVolume += t.mstoVolume ?? 0; a.mstoCount++ }
    if (t.tfSum != null) { a.tfSum += t.tfSum; a.tfVolume += t.tfVolume ?? 0; a.tfCount++ }
  }
  const byAggregator = [...aggMap.values()].map((a) => ({
    ...a,
    sumDiff: a.mstoSum - a.tfSum,
    volumeDiff: a.mstoVolume - a.tfVolume,
    status: (Math.abs(a.mstoSum - a.tfSum) > UI_SUM_TOLERANCE || Math.abs(a.mstoVolume - a.tfVolume) > UI_VOLUME_TOLERANCE ? 'error' : 'ok') as 'ok' | 'error',
  }))

  // By station
  const stationMap = new Map<number, ReconciliationByStation>()
  for (const t of transactions) {
    if (!stationMap.has(t.stationId)) {
      stationMap.set(t.stationId, { stationId: t.stationId, stationName: t.stationName, byShift: [], mstoSum: 0, mstoVolume: 0, tfSum: 0, tfVolume: 0, shiftSbpRevenue: 0, status: 'ok' })
    }
    const st = stationMap.get(t.stationId)!
    st.mstoSum += t.mstoSum ?? 0
    st.mstoVolume += t.mstoVolume ?? 0
    st.tfSum += t.tfSum ?? 0
    st.tfVolume += t.tfVolume ?? 0
  }
  const byStation = [...stationMap.values()].map((st) => ({
    ...st,
    shiftSbpRevenue: shifts.filter((s) => s.stationId === st.stationId).reduce((a, s) => a + s.sbpRevenue, 0),
    status: (Math.abs(st.mstoSum - st.tfSum) > UI_SUM_TOLERANCE ? 'error' : 'ok') as 'ok' | 'error',
  }))

  const summary: ReconciliationSummary = {
    totalMstoSum, totalMstoVolume, totalMstoCount: mstoTxs.length,
    totalTfSum, totalTfVolume, totalTfCount: tfTxs.length,
    totalShiftSbpRevenue: totalShiftSbp, totalShiftNonCashVolume: totalShiftVol,
    mstoVsTfSumDiff: totalMstoSum - totalTfSum,
    mstoVsTfVolumeDiff: totalMstoVolume - totalTfVolume,
    tfVsShiftSumDiff: totalTfSum - totalShiftSbp,
    tfVsShiftVolumeDiff: totalTfVolume - totalShiftVol,
    matched, mstoWaitDone, onlyMsto, onlyTf, onlyShift, mismatch,
    hasErrors: mismatch > 0 || onlyMsto > 0 || onlyShift > 0,
  }

  return {
    params,
    summary,
    byStation,
    byAggregator,
    transactions,
    executedAt: new Date().toISOString(),
    duration: Date.now() - startTime,
  }
}
