/**
 * Нормализация сменного отчёта из STS API → ShiftRecord.
 * Извлекает бухгалтерски значимые данные: продажи, каналы оплаты, резервуары.
 */

import type { StsShiftReport, ShiftRecord, FuelSaleSummary, PaymentChannelSummary, TankSummary } from './types'
import { getStationName } from '../settingsService'

export function normalizeShift(stationId: number, shiftNumber: number, dtOpen: string, dtClose: string | null, report: StsShiftReport): ShiftRecord {
  // Итоги по видам топлива (из psm.total)
  const fuelSales: FuelSaleSummary[] = (report.psm?.total ?? []).map((t) => ({
    fuelCode: t.service.service_code,
    fuelName: t.service.service_name,
    volumeLiters: t.release.quantity,
    massKg: t.release.cost,
    amount: t.release.amount,
    tankNumber: t.tank,
  }))

  // Продажи по каналам оплаты (из sales)
  const paymentChannels: PaymentChannelSummary[] = (report.sales ?? []).map((s) => {
    const fuels = (s.fuel ?? []).map((f) => ({
      fuelCode: f.service.service_code,
      fuelName: f.service.service_name,
      volumeLiters: parseFloat(f.release.volume) || 0,
      amount: parseFloat(f.release.cost) || 0,
      discount: f.release.discount || 0,
    }))
    return {
      channelId: s.pay_type.id,
      channelName: s.pay_type.name,
      fuels,
      totalAmount: fuels.reduce((sum, f) => sum + f.amount, 0),
    }
  })

  // Резервуары (из release)
  const tanks: TankSummary[] = (report.release ?? []).map((r) => ({
    tankNumber: r.tank,
    fuelCode: r.service.service_code,
    fuelName: r.service.service_name,
    densityStart: r.density_beg,
    densityEnd: r.density_end,
    volumeStart: parseFloat(r.doc_beg.volume) || 0,
    volumeEnd: parseFloat(r.doc_end.volume) || 0,
    received: parseFloat(r.receipt.volume) || 0,
    released: parseFloat(r.release.volume) || 0,
    rest: parseFloat(r.rest.volume) || 0,
  }))

  const totalVolumeLiters = fuelSales.reduce((sum, f) => sum + f.volumeLiters, 0)
  const totalAmount = fuelSales.reduce((sum, f) => sum + f.amount, 0)

  return {
    id: `${stationId}-${shiftNumber}`,
    stationId,
    stationName: getStationName(stationId),
    shiftNumber,
    openedAt: dtOpen,
    closedAt: dtClose,
    status: dtClose ? 'closed' : 'open',
    fuelSales,
    paymentChannels,
    tanks,
    receiptsCount: (report.receipt ?? []).length,
    moneyOps: report.money ?? [],
    totalVolumeLiters: Math.round(totalVolumeLiters * 100) / 100,
    totalAmount: Math.round(totalAmount * 100) / 100,
    raw: report,
  }
}
