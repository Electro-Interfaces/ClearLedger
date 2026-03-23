/**
 * Сервис синхронизации канала — загрузка данных из источника.
 * MVP: поддержка REST API (STS) — смены и ТТН.
 */

import type { Channel, SyncLogEntry, SyncResult } from '@/types/channel'
import { updateChannel, addSyncLog } from './channelService'
import { stsLogin, stsGetShifts, stsGetShiftReport, stsGetReceipts } from './fuel/stsApiClient'
import { normalizeShift } from './fuel/shiftNormalizer'
import { normalizeReceipt } from './fuel/receiptNormalizer'
import { getItem, setItem } from './storage'
import type { ShiftRecord, ReceiptRecord } from './fuel/types'

const LOADED_DOCS_KEY = 'gig-loaded-docs'

/** Загруженный документ в хранилище */
export interface LoadedDocument {
  id: string
  channelId: string
  streamId: string
  docType: 'shift_report' | 'receipt' | 'price'
  fingerprint: string
  title: string
  stationId: number
  date: string
  data: ShiftRecord | ReceiptRecord | unknown
  catalog: string
  loadedAt: string
}

function getLoadedDocs(): LoadedDocument[] {
  return getItem<LoadedDocument[]>(LOADED_DOCS_KEY, [])
}

function saveLoadedDoc(doc: LoadedDocument): boolean {
  const docs = getLoadedDocs()
  const exists = docs.some((d) => d.fingerprint === doc.fingerprint)
  if (exists) return false // дубликат
  docs.push(doc)
  setItem(LOADED_DOCS_KEY, docs)
  return true
}

export function getAllLoadedDocs(): LoadedDocument[] {
  return getLoadedDocs()
}

function makeFingerprint(parts: string[]): string {
  return parts.join('|')
}

function logEntry(level: SyncLogEntry['level'], event: SyncLogEntry['event'], message: string): SyncLogEntry {
  return { timestamp: new Date().toISOString(), level, event, message }
}

/** Параметры синхронизации */
export interface SyncOptions {
  /** Какие потоки обновлять (id потоков) */
  streamIds?: string[]
  /** Станции для загрузки */
  stationCodes?: number[]
  /** Политика дубликатов */
  duplicatePolicy?: 'skip' | 'warn' | 'overwrite'
  /** Callback для обновления прогресса */
  onProgress?: (loaded: number, total: number, message: string) => void
}

/** Синхронизация REST API канала (STS) */
export async function syncRestChannel(channel: Channel, opts: SyncOptions = {}): Promise<SyncResult> {
  const log: SyncLogEntry[] = []
  const startedAt = new Date().toISOString()
  let loaded = 0
  let skipped = 0
  let duplicates = 0
  let errors = 0

  const url = channel.config.url || channel.endpoint || ''
  const login = channel.config.login || ''
  const password = channel.config.password || ''
  const systemCode = Number(channel.config.systemCode) || 65
  const policy = opts.duplicatePolicy ?? channel.duplicatePolicy ?? 'skip'

  // Определяем какие потоки обновлять
  const activeStreams = channel.streams.filter((s) => {
    if (!s.enabled) return false
    if (opts.streamIds && !opts.streamIds.includes(s.id)) return false
    return true
  })

  if (activeStreams.length === 0) {
    log.push(logEntry('warn', 'SYNC', 'Нет активных потоков для загрузки'))
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped, duplicates, errors, log }
  }

  log.push(logEntry('info', 'SYNC', `Загрузка начата (${activeStreams.length} поток(ов))`))
  opts.onProgress?.(0, 0, 'Авторизация...')

  // 1. Авторизация
  try {
    const baseUrl = import.meta.env.DEV ? '/tms' : url
    await stsLogin(baseUrl, login, password)
    log.push(logEntry('success', 'AUTH', 'Авторизация OK'))
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    log.push(logEntry('error', 'ERROR', `Авторизация: ${msg}`))
    addSyncLog(channel.id, log)
    updateChannel(channel.id, { status: 'error', errorMessage: msg })
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped, duplicates, errors: 1, log }
  }

  // 2. Получить список смен
  let shifts: Awaited<ReturnType<typeof stsGetShifts>> = []
  try {
    shifts = await stsGetShifts(systemCode)
    log.push(logEntry('info', 'LOAD', `Получено ${shifts.length} смен`))
  } catch (err) {
    log.push(logEntry('error', 'ERROR', `Список смен: ${err instanceof Error ? err.message : err}`))
    errors++
  }

  // Определить станции
  const stationCodes = opts.stationCodes ?? [Number(Object.values(channel.config).find((v) => !isNaN(Number(v))) || 0)]

  // 3. Загрузка по потокам
  for (const stream of activeStreams) {
    opts.onProgress?.(loaded, shifts.length, `Поток: ${stream.name}`)

    if (stream.docType === 'shift_report') {
      // Загрузка сменных отчётов
      let streamLoaded = 0
      let streamDups = 0

      for (const shift of shifts) {
        const stationId = stationCodes[0] || 0 // MVP: первая станция
        const fp = makeFingerprint(['shift', String(stationId), String(shift.shift), shift.dt_open || ''])

        // Проверка дубликата
        const docs = getLoadedDocs()
        if (docs.some((d) => d.fingerprint === fp)) {
          if (policy === 'skip') { streamDups++; continue }
        }

        try {
          const report = await stsGetShiftReport(stationId, shift.shift, systemCode)
          const normalized = normalizeShift(stationId, report)

          const doc: LoadedDocument = {
            id: `shift-${stationId}-${shift.shift}`,
            channelId: channel.id,
            streamId: stream.id,
            docType: 'shift_report',
            fingerprint: fp,
            title: `Смена №${shift.shift} — ${normalized.stationName}`,
            stationId,
            date: shift.dt_open || new Date().toISOString(),
            data: normalized,
            catalog: stream.catalogTemplate
              .replace('{станция}', `АЗС-${stationId}`)
              .replace('{год}', new Date(shift.dt_open || '').getFullYear().toString())
              .replace('{месяц}', String(new Date(shift.dt_open || '').getMonth() + 1).padStart(2, '0')),
            loadedAt: new Date().toISOString(),
          }

          if (saveLoadedDoc(doc)) {
            streamLoaded++
            loaded++
          } else {
            streamDups++
            duplicates++
          }
        } catch (err) {
          log.push(logEntry('error', 'ERROR', `Смена ${shift.shift}: ${err instanceof Error ? err.message : err}`))
          errors++
        }

        opts.onProgress?.(loaded, shifts.length, `Смена №${shift.shift}`)
      }

      log.push(logEntry('info', 'LOAD', `${stream.name}: ${streamLoaded} загружено, ${streamDups} дубликатов`))
      duplicates += streamDups

    } else if (stream.docType === 'receipt') {
      // Загрузка ТТН
      let streamLoaded = 0

      for (const shift of shifts) {
        const stationId = stationCodes[0] || 0
        try {
          const receipts = await stsGetReceipts(stationId, shift.shift, systemCode)
          for (const raw of receipts) {
            const normalized = normalizeReceipt(stationId, raw)
            const fp = makeFingerprint(['receipt', String(stationId), raw.ttn, String(raw.fuel)])

            const doc: LoadedDocument = {
              id: `receipt-${normalized.id}`,
              channelId: channel.id,
              streamId: stream.id,
              docType: 'receipt',
              fingerprint: fp,
              title: `ТТН ${raw.ttn} — ${normalized.fuelName}`,
              stationId,
              date: raw.dt,
              data: normalized,
              catalog: stream.catalogTemplate
                .replace('{станция}', `АЗС-${stationId}`)
                .replace('{год}', new Date(raw.dt).getFullYear().toString())
                .replace('{месяц}', String(new Date(raw.dt).getMonth() + 1).padStart(2, '0')),
              loadedAt: new Date().toISOString(),
            }

            if (saveLoadedDoc(doc)) {
              streamLoaded++
              loaded++
            } else {
              duplicates++
            }
          }
        } catch {
          // Не все смены имеют ТТН — это нормально
        }
      }

      log.push(logEntry('info', 'LOAD', `${stream.name}: ${streamLoaded} загружено`))
    }
  }

  // 4. Финализация
  const finishedAt = new Date().toISOString()
  log.push(logEntry('success', 'DONE', `Завершено: ${loaded} загружено, ${duplicates} дубликатов, ${errors} ошибок`))

  addSyncLog(channel.id, log)
  updateChannel(channel.id, {
    status: errors > 0 ? 'error' : 'active',
    docsLoaded: (channel.docsLoaded || 0) + loaded,
    lastSync: finishedAt,
    errorMessage: errors > 0 ? `${errors} ошибок при загрузке` : undefined,
  })

  opts.onProgress?.(loaded, loaded, 'Готово')

  return { channelId: channel.id, startedAt, finishedAt, loaded, skipped, duplicates, errors, log }
}
