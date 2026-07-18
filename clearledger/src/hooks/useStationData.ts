/**
 * Хуки данных в разрезе КОНКРЕТНОЙ станции (для окна станции / cockpit).
 *
 * - useStationLastShift — последняя закрытая смена + её детальный отчёт (резервуары,
 *   продажи, оплаты). Переиспользуется вкладками «Оборудование» и «Реализация».
 * - useStationPnL / useStationPaymentMix — обёртки над analyticsService (голые
 *   async-функции) в useQuery с фильтром station_id.
 */
import { useQuery } from '@tanstack/react-query'
import { useShifts, useShiftReport } from './useFuel'
import { getPnL, getPaymentMix } from '@/services/analyticsService'
import type { StsShift } from '@/services/fuel/types'

/** Последняя закрытая смена станции + её сменный отчёт. */
export function useStationLastShift(stationId: number | null) {
  const shiftsQ = useShifts(stationId ?? undefined)
  const closed = (shiftsQ.data ?? []).filter((s) => s.dt_close)
  const lastShift = closed.reduce<StsShift | null>(
    (acc, s) => (!acc || s.shift > acc.shift ? s : acc),
    null,
  )
  const reportQ = useShiftReport(stationId ?? 0, lastShift?.shift ?? 0, lastShift?.dt_open, lastShift?.dt_close)
  return { shiftsQ, closedCount: closed.length, lastShift, reportQ }
}

/** P&L станции за период (revenue/cogs/маржа/литры). */
export function useStationPnL(stationId: number | null, companyId: string, from: string, to: string) {
  return useQuery({
    queryKey: ['station-pnl', companyId, stationId, from, to],
    queryFn: () => getPnL({
      companyId, dateFrom: from, dateTo: to,
      stationId: String(stationId), groupBy: 'station',
    }),
    enabled: !!stationId && !!companyId,
    staleTime: 5 * 60 * 1000,
  })
}

/** Структура оплат станции за период (наличные/карты/талоны/прочее). */
export function useStationPaymentMix(stationId: number | null, companyId: string, from: string, to: string) {
  return useQuery({
    queryKey: ['station-payment-mix', companyId, stationId, from, to],
    queryFn: () => getPaymentMix({
      companyId, dateFrom: from, dateTo: to, stationId: String(stationId),
    }),
    enabled: !!stationId && !!companyId,
    staleTime: 5 * 60 * 1000,
  })
}
