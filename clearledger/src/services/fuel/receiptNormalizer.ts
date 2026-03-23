/**
 * Нормализация ТТН (поступления) из STS API → ReceiptRecord.
 */

import type { StsReceipt, ReceiptRecord } from './types'
import { getStationName } from '../settingsService'

function parseNum(v: string | number | undefined): number {
  if (v == null) return 0
  const n = typeof v === 'string' ? parseFloat(v) : v
  return isNaN(n) ? 0 : n
}

export function normalizeReceipt(stationId: number, raw: StsReceipt): ReceiptRecord {
  const docVol = parseNum(raw.doc?.volume)
  const docMass = parseNum(raw.doc?.amount)
  const docCost = parseNum(raw.doc?.cost)
  const factVol = parseNum(raw.fact?.volume)
  const factMass = parseNum(raw.fact?.amount)
  const factCost = parseNum(raw.fact?.cost)

  const density = docVol > 0 && docMass > 0 ? Math.round((docMass / docVol) * 10000) / 10000 : 0

  return {
    id: `${stationId}-${raw.shift}-${raw.ttn}`,
    stationId,
    stationName: getStationName(stationId),
    shiftNumber: raw.shift,
    ttn: raw.ttn,
    supplierName: raw.base?.name || '—',
    fuelName: raw.service?.service_name || `Топливо ${raw.fuel}`,
    fuelCode: raw.fuel,
    tankNumber: raw.tank,
    docVolumeLiters: docVol,
    docMassKg: docMass,
    docCost,
    factVolumeLiters: factVol,
    factMassKg: factMass,
    factCost,
    density,
    receivedAt: raw.dt,
    diffVolume: Math.round((factVol - docVol) * 100) / 100,
    diffMass: Math.round((factMass - docMass) * 100) / 100,
  }
}
