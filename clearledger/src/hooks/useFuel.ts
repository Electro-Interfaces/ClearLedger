/**
 * React Query хуки для работы с STS API.
 */

import { useQuery } from '@tanstack/react-query'
import { stsGetShifts, stsGetShiftReport, stsGetReceipts } from '@/services/fuel/stsApiClient'
import { normalizeShift } from '@/services/fuel/shiftNormalizer'
import { normalizeReceipt } from '@/services/fuel/receiptNormalizer'
import { getSettings, getStationCodes } from '@/services/settingsService'
import type { ShiftRecord, ReceiptRecord, FuelKpi, StsShift } from '@/services/fuel/types'

/** Список смен по всем настроенным станциям */
export function useShifts(stationId?: number) {
  const settings = getSettings()
  const enabled = !!settings.stsLogin && !!settings.stsPassword

  return useQuery<StsShift[]>({
    queryKey: ['sts-shifts', stationId, settings.stsSystemCode],
    queryFn: () => stsGetShifts(settings.stsSystemCode, stationId),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  })
}

/** Детальный сменный отчёт */
export function useShiftReport(stationId: number, shiftNumber: number) {
  const settings = getSettings()
  const enabled = !!settings.stsLogin && !!settings.stsPassword && stationId > 0 && shiftNumber > 0

  return useQuery<ShiftRecord>({
    queryKey: ['sts-shift-report', stationId, shiftNumber],
    queryFn: async () => {
      const report = await stsGetShiftReport(stationId, shiftNumber)
      return normalizeShift(stationId, report)
    },
    enabled,
    staleTime: 2 * 60 * 1000,
  })
}

/** Поступления (ТТН) по смене */
export function useReceipts(stationId: number, shiftNumber: number) {
  const settings = getSettings()
  const enabled = !!settings.stsLogin && !!settings.stsPassword && stationId > 0 && shiftNumber > 0

  return useQuery<ReceiptRecord[]>({
    queryKey: ['sts-receipts', stationId, shiftNumber],
    queryFn: async () => {
      const raw = await stsGetReceipts(stationId, shiftNumber)
      return raw.map((r) => normalizeReceipt(stationId, r))
    },
    enabled,
    staleTime: 2 * 60 * 1000,
  })
}

/** Все ТТН по станции (из receipt-секций shift_report, кэшировано) */
export function useAllReceipts(stationId?: number) {
  const settings = getSettings()
  const enabled = !!settings.stsLogin && !!settings.stsPassword

  return useQuery<{ shift: number; ttn: string; fuel: string; docVolume: number; factVolume: number; dt: string }[]>({
    queryKey: ['sts-all-receipts', stationId, settings.stsSystemCode],
    queryFn: async () => {
      const shifts = await stsGetShifts(settings.stsSystemCode, stationId)
      const closedShifts = shifts.filter((s) => s.dt_close)
      const results: { shift: number; ttn: string; fuel: string; docVolume: number; factVolume: number; dt: string }[] = []

      // Загружаем receipt-секции параллельно (батчами по 10)
      const station = stationId ?? settings.stations[0]?.code ?? 0
      for (let i = 0; i < closedShifts.length; i += 10) {
        const batch = closedShifts.slice(i, i + 10)
        const reports = await Promise.all(
          batch.map((s) => stsGetShiftReport(station, s.shift).catch(() => null)),
        )
        for (let j = 0; j < reports.length; j++) {
          const report = reports[j]
          if (!report) continue
          const receipts = (report as Record<string, unknown>).receipt as Array<Record<string, unknown>> | undefined
          if (!receipts) continue
          for (const r of receipts) {
            const svc = r.service as Record<string, unknown> | undefined
            const doc = r.doc as Record<string, unknown> | undefined
            const fact = r.fact as Record<string, unknown> | undefined
            results.push({
              shift: batch[j].shift,
              ttn: String(r.ttn ?? ''),
              fuel: String(svc?.service_name ?? ''),
              docVolume: Number(doc?.volume ?? 0),
              factVolume: Number(fact?.volume ?? 0),
              dt: String(r.dt ?? batch[j].dt_open ?? ''),
            })
          }
        }
      }
      return results
    },
    enabled,
    staleTime: 10 * 60 * 1000,
  })
}

/** Агрегированные KPI по всем станциям */
export function useFuelKpi() {
  const settings = getSettings()
  const stations = getStationCodes()
  const enabled = !!settings.stsLogin && !!settings.stsPassword && stations.length > 0

  return useQuery<FuelKpi>({
    queryKey: ['sts-kpi', stations, settings.stsSystemCode],
    queryFn: async () => {
      const allShifts = await stsGetShifts(settings.stsSystemCode)
      const open = allShifts.filter((s) => !s.dt_close)

      return {
        stationsCount: stations.length,
        shiftsTotal: allShifts.length,
        shiftsOpen: open.length,
        totalSalesLiters: 0, // нужен отдельный запрос, на KPI достаточно кол-ва смен
        totalSalesAmount: 0,
        receiptsCount: 0,
      }
    },
    enabled,
    staleTime: 5 * 60 * 1000,
  })
}
