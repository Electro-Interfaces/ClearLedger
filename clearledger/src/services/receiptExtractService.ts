/**
 * Извлечение ТТН (поступления топлива) из загруженных сменных отчётов.
 * Каждая ТТН из raw.receipt становится отдельным документом в каталоге.
 */

import { getAllLoadedDocs, type LoadedDocument } from './channelSyncService'
import { getItem, setItem } from './storage'
import type { ShiftRecord, StsShiftReceipt } from './fuel/types'
import { getStationName } from './settingsService'
import { updateChannel, addSyncLog } from './channelService'
import type { Channel, SyncLogEntry, SyncResult } from '@/types/channel'

const LOADED_DOCS_KEY = 'gig-loaded-docs'

/** Нормализованная ТТН (слив бензовоза) */
export interface DeliveryRecord {
  id: string
  /** Номер ТТН */
  ttn: string
  stationId: number
  stationName: string
  shiftNumber: number
  /** Вид топлива */
  fuelCode: number
  fuelName: string
  tankNumber: number
  /** Поставщик */
  supplierName: string
  /** Документальные данные */
  docVolumeLiters: number
  docMassKg: number
  docDensity: number
  docTemp: number
  /** Фактические данные */
  factVolumeLiters: number
  factMassKg: number
  factDensity: number
  factTemp: number
  /** Расхождения */
  diffVolumeLiters: number
  diffMassKg: number
  /** Дата слива */
  deliveredAt: string
  /** Ссылка на исходный сменный отчёт */
  sourceShiftId: string
}

function normalizeReceipt(stationId: number, shiftNumber: number, r: StsShiftReceipt): DeliveryRecord {
  const docVol = parseFloat(r.doc.volume) || 0
  const docMass = parseFloat(r.doc.amount) || 0
  const factVol = parseFloat(r.fact.volume) || 0
  const factMass = parseFloat(r.fact.amount) || 0

  return {
    id: `ttn-${stationId}-${shiftNumber}-${r.ttn}-${r.service.service_code}`,
    ttn: r.ttn,
    stationId,
    stationName: getStationName(stationId),
    shiftNumber,
    fuelCode: r.service.service_code,
    fuelName: r.service.service_name,
    tankNumber: r.tank,
    supplierName: r.base?.name || '—',
    docVolumeLiters: docVol,
    docMassKg: docMass,
    docDensity: r.doc.density,
    docTemp: r.doc.temp,
    factVolumeLiters: factVol,
    factMassKg: factMass,
    factDensity: r.fact.density,
    factTemp: r.fact.temp,
    diffVolumeLiters: Math.round((factVol - docVol) * 1000) / 1000,
    diffMassKg: Math.round((factMass - docMass) * 1000) / 1000,
    deliveredAt: r.dt,
    sourceShiftId: `${stationId}-${shiftNumber}`,
  }
}

function logEntry(level: SyncLogEntry['level'], event: SyncLogEntry['event'], message: string): SyncLogEntry {
  return { timestamp: new Date().toISOString(), level, event, message }
}

/**
 * Извлечь ТТН из всех загруженных сменных отчётов.
 * Создаёт отдельные документы типа 'delivery' в хранилище.
 */
export async function extractDeliveries(channel: Channel, opts?: {
  onProgress?: (loaded: number, total: number, msg: string) => void
}): Promise<SyncResult> {
  const log: SyncLogEntry[] = []
  const startedAt = new Date().toISOString()
  let loaded = 0
  let duplicates = 0
  let errors = 0

  // Найти все загруженные сменные отчёты
  const allDocs = getAllLoadedDocs()
  const shiftDocs = allDocs.filter((d) => d.docType === 'shift_report')

  if (shiftDocs.length === 0) {
    log.push(logEntry('warn', 'SYNC', 'Нет загруженных сменных отчётов — сначала загрузите смены'))
    addSyncLog(channel.id, log)
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped: 0, duplicates, errors: 0, log }
  }

  log.push(logEntry('info', 'SYNC', `Извлечение ТТН из ${shiftDocs.length} сменных отчётов`))

  // Поток delivery
  const deliveryStream = (channel.streams ?? []).find((s) => s.enabled)

  let totalReceipts = 0

  for (const shiftDoc of shiftDocs) {
    const shift = shiftDoc.data as ShiftRecord
    if (!shift?.raw?.receipt?.length) continue

    totalReceipts += shift.raw.receipt.length
    opts?.onProgress?.(loaded, totalReceipts, `Смена №${shift.shiftNumber}`)

    for (const rawReceipt of shift.raw.receipt) {
      const record = normalizeReceipt(shift.stationId, shift.shiftNumber, rawReceipt)
      const fp = `delivery|${record.stationId}|${record.ttn}|${record.fuelCode}|${record.shiftNumber}`

      // Проверка дубликата
      if (allDocs.some((d) => d.fingerprint === fp)) {
        duplicates++
        continue
      }

      try {
        const doc: LoadedDocument = {
          id: record.id,
          channelId: channel.id,
          streamId: deliveryStream?.id ?? '',
          docType: 'delivery',
          fingerprint: fp,
          title: `ТТН ${record.ttn} — ${record.fuelName} (${record.docVolumeLiters.toFixed(0)} л)`,
          stationId: record.stationId,
          date: record.deliveredAt,
          data: record,
          catalog: `/Поступления/АЗС-${record.stationId}/${new Date(record.deliveredAt).getFullYear()}`,
          loadedAt: new Date().toISOString(),
        }

        // Сохранить
        const docs = getItem<LoadedDocument[]>(LOADED_DOCS_KEY, [])
        if (docs.some((d) => d.fingerprint === fp)) {
          duplicates++
        } else {
          docs.push(doc)
          setItem(LOADED_DOCS_KEY, docs)
          loaded++
        }
      } catch (err) {
        log.push(logEntry('error', 'ERROR', `ТТН ${rawReceipt.ttn}: ${err instanceof Error ? err.message : err}`))
        errors++
      }
    }
  }

  const finishedAt = new Date().toISOString()
  log.push(logEntry('success', 'DONE', `Готово: ${loaded} ТТН извлечено, ${duplicates} дубликатов, ${errors} ошибок`))

  addSyncLog(channel.id, log)
  updateChannel(channel.id, {
    status: errors > 0 ? 'error' : 'active',
    docsLoaded: (channel.docsLoaded || 0) + loaded,
    lastSync: finishedAt,
  })

  opts?.onProgress?.(loaded, loaded, 'Готово')
  return { channelId: channel.id, startedAt, finishedAt, loaded, skipped: 0, duplicates, errors, log }
}
