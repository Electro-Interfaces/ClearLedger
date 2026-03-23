/**
 * Нормализация сменного отчёта из STS API → ShiftRecord.
 */

import type { StsShiftReport, ShiftRecord } from './types'
import { getStationName } from '../settingsService'

export function normalizeShift(stationId: number, report: StsShiftReport): ShiftRecord {
  const info = report.shift_info

  const totalSalesLiters = report.tanks.reduce((sum, t) => sum + (t.sales || 0), 0)
  const totalSalesAmount = report.pumps.reduce((sum, p) => sum + (p.amount || 0), 0)

  return {
    id: `${stationId}-${info.shift_number}`,
    stationId,
    stationName: getStationName(stationId),
    shiftNumber: info.shift_number,
    openedAt: info.dt_open,
    closedAt: info.dt_close,
    operator: info.operator || '—',
    tanks: report.tanks,
    pumps: report.pumps,
    payments: report.payments,
    cashOperations: report.cash_operations || [],
    totalSalesLiters: Math.round(totalSalesLiters * 100) / 100,
    totalSalesAmount: Math.round(totalSalesAmount * 100) / 100,
    status: info.dt_close ? 'closed' : 'open',
  }
}
