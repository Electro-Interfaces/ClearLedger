/**
 * Преобразование нашей детали смены (бэкенд /fuel/shifts/{id}) в формат
 * эталонного просмотрщика TradeFrame (ShiftDetails) через ShiftReportAdapterV2.
 *
 * Путь 1 (точный): смена загружена с raw_report (сырой отчёт STS) — адаптер
 *   строит форму ровно как в TradePoint, включая «Безналичную реализацию»
 *   по сырым pay_type (Купон/МобилПр и т.п.).
 * Путь 2 (реконструкция): старые смены без raw_report — собираем синтетический
 *   отчёт из детальных таблиц (pumps/tanks/cash/receipts/sales). Реализация при
 *   этом приближённая: продажи восстановлены из FuelShiftSale по КАНАЛУ оплаты
 *   (купон/прокачка были отброшены при ingest). Точные данные — после переигровки.
 */

import { ShiftReportAdapterV2 } from '@/services/adapters/shiftReportAdapterV2'
import type { ShiftDetails } from '@/types/shift-reports-v2'
import type { ShiftDetail } from '@/services/fuel/fuelMappingService'

/** Канал оплаты → представительное имя pay_type (для классификатора). */
const CHANNEL_PAYNAME: Record<string, string> = {
  retail_cash: 'Наличные',
  retail_card: 'Банковские карты',
  cards: 'Корп. карты',
  online: 'МобилПр.',
  voucher: 'Талоны',
  ledger: 'Ведомость',
  writeoff_fuel: 'Прочее',
}

function fuelNameByCode(d: ShiftDetail, code: number): string {
  const p = d.pumps.find((x) => x.fuel_code === code)
  if (p) return p.fuel_type
  const t = d.tanks.find((x) => x.fuel_code === code)
  if (t) return t.fuel_type
  return `Код ${code}`
}

/** Синтетический сырой отчёт STS из наших детальных таблиц (для старых смен). */
function reconstructReport(d: ShiftDetail): Record<string, any> {
  const data = d.pumps.map((p) => ({
    pump: p.pump_number,
    nozzle: p.nozzle || '',
    psm_beg: p.psm_beg ?? 0,
    psm_end: p.psm_end ?? 0,
    price: p.price ?? 0,
    tank: p.tank_number ?? 0,
    density: p.density ?? 0,
    service: { service_code: p.fuel_code ?? 0, service_name: p.fuel_type },
    release: {
      volume: p.sales_volume,
      amount: p.sales_volume * (p.density ?? 0),
      cost: p.amount,
    },
  }))

  const release = d.tanks.map((t) => ({
    tank: t.tank_number,
    service: { service_code: t.fuel_code ?? 0, service_name: t.fuel_type },
    doc_beg: { volume: t.volume_start },
    doc_end: { volume: t.volume_end },
    receipt: { volume: t.volume_received },
    release: { volume: t.sales },
    density_beg: t.density_beg,
    density_end: t.density,
    temp_end: t.temp_end,
    level_end: t.level_end,
    water: { level: t.water_level, volume: t.water_volume },
  }))

  const money = d.cash_movements.map((m) => ({
    shift: d.shift_number,
    pos: m.pos_number,
    operation: { id: m.operation_id, name: m.operation_name },
    volume: m.amount,
  }))

  const receipt = d.receipts.map((r) => ({
    shift: d.shift_number,
    tank: 0,
    ttn: r.ttn,
    service: { service_code: 0, service_name: r.fuel_name },
    base: { name: r.supplier },
    doc: { volume: r.doc_volume_liters, density: r.density },
    fact: { volume: r.fact_volume_liters },
    dt: r.created_at,
  }))

  // sales — группируем FuelShiftSale по каналу, имитируя секцию sales STS.
  const byChannel = new Map<string, any>()
  for (const s of d.sales) {
    if (!byChannel.has(s.payment_channel)) {
      byChannel.set(s.payment_channel, {
        pay_type: { name: CHANNEL_PAYNAME[s.payment_channel] ?? s.payment_channel },
        fuel: [] as any[],
      })
    }
    byChannel.get(s.payment_channel).fuel.push({
      service: { service_code: s.fuel_code, service_name: fuelNameByCode(d, s.fuel_code) },
      release: { volume: s.liters, cost: s.amount, discount: s.discount },
    })
  }

  return { psm: { data, total: [] }, release, money, receipt, sales: Array.from(byChannel.values()) }
}

export interface BuiltShiftDetails {
  details: ShiftDetails
  /** true — построено из сырого отчёта STS (точная форма); false — реконструкция. */
  exact: boolean
}

export function buildShiftDetails(
  d: ShiftDetail,
  tankThreshold = 10,
  fuelName?: (code?: number | null, fallback?: string | null) => string,
): BuiltShiftDetails {
  const exact = !!(d.raw_report && Object.keys(d.raw_report).length > 0)
  const report = exact ? (d.raw_report as Record<string, any>) : reconstructReport(d)
  const shiftInfo = {
    dt_open: d.opened_at || undefined,
    dt_close: d.closed_at || undefined,
    operator: d.operator || undefined,
  }
  const details = ShiftReportAdapterV2.toDetails(
    report,
    d.shift_number,
    0,
    d.station_code,
    d.station_name ?? `АЗС №${d.station_code}`,
    shiftInfo,
    tankThreshold,
  )
  // Единое каноническое имя топлива (из справочника, согласовано с 1С) по fuelCode.
  if (fuelName) {
    for (const n of details.nozzleReadings) n.fuelName = fuelName(n.fuelCode, n.fuelName)
    for (const t of details.tanks) t.fuelName = fuelName(t.fuelCode, t.fuelName)
    for (const s of details.salesBreakdown) s.fuelName = fuelName(s.fuelCode, s.fuelName)
    for (const f of details.fuelSales) f.fuelName = fuelName(f.fuelCode, f.fuelName)
    for (const r of details.receipts) r.fuelName = fuelName(r.fuelCode, r.fuelName)
  }
  return { details, exact }
}
