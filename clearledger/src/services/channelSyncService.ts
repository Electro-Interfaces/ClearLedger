/**
 * Сервис синхронизации — загрузка данных из источников.
 */

import type { Channel, SyncLogEntry, SyncResult } from '@/types/channel'
import { getChannelStations } from '@/types/channel'
import { updateChannel, addSyncLog } from './channelService'
import { getSource } from './sourceService'
import { stsLogin, stsGetShifts, stsGetShiftReport } from './fuel/stsApiClient'
import { normalizeShift } from './fuel/shiftNormalizer'
import { mstoLogin, mstoGetTransactions, mstoGetTariffs } from './msto/mstoApiClient'
import { tradecorpLogin, tradecorpGetTransactions } from './tradecorp/tradecorpApiClient'
import { getItem, setItem } from './storage'
import type { ShiftRecord } from './fuel/types'

const LOADED_DOCS_KEY = 'gig-loaded-docs'

/** Загруженный документ в хранилище */
export interface LoadedDocument {
  id: string
  channelId: string
  streamId: string
  docType: string
  fingerprint: string
  title: string
  stationId: number
  date: string
  data: ShiftRecord | unknown
  catalog: string
  loadedAt: string
}

function getLoadedDocs(): LoadedDocument[] {
  return getItem<LoadedDocument[]>(LOADED_DOCS_KEY, [])
}

function saveLoadedDoc(doc: LoadedDocument): boolean {
  const docs = getLoadedDocs()
  if (docs.some((d) => d.fingerprint === doc.fingerprint)) return false
  docs.push(doc)
  setItem(LOADED_DOCS_KEY, docs)
  return true
}

export function getAllLoadedDocs(): LoadedDocument[] {
  return getLoadedDocs()
}

function logEntry(level: SyncLogEntry['level'], event: SyncLogEntry['event'], message: string): SyncLogEntry {
  return { timestamp: new Date().toISOString(), level, event, message }
}

export interface SyncOptions {
  onProgress?: (loaded: number, total: number, message: string) => void
}

// ─── STS (REST) Sync ────────────────────────────────────────

/** Синхронизация REST-канала — загрузка сменных отчётов */
export async function syncRestChannel(channel: Channel, opts: SyncOptions = {}): Promise<SyncResult> {
  const log: SyncLogEntry[] = []
  const startedAt = new Date().toISOString()
  let loaded = 0
  let duplicates = 0
  let errors = 0

  const primarySourceId = channel.sourceIds?.[0] ?? channel.sourceId ?? ''
  const source = getSource(primarySourceId)
  const conn = source?.connection ?? {}
  const login = conn.login || ''
  const password = conn.password || ''

  // Берём станции из канала. Каждая несёт свой system_id — сеть АЗС в STS.
  const stations = getChannelStations(channel)
  if (stations.length === 0) {
    log.push(logEntry('error', 'ERROR', 'Не указаны станции (config.stations)'))
    addSyncLog(channel.id, log)
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped: 0, duplicates, errors: 1, log }
  }

  const shiftStream = (channel.streams ?? []).find((s) => s.docTypeId === 'shift_report' && s.enabled)
  if (!shiftStream) {
    log.push(logEntry('warn', 'SYNC', 'Поток shift_report не найден или отключён'))
    addSyncLog(channel.id, log)
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped: 0, duplicates, errors: 0, log }
  }

  const stationsLabel = stations
    .map((s) => `${s.code}@sys${s.systemId}`)
    .join(', ')
  log.push(logEntry('info', 'SYNC', `Загрузка сменных отчётов (станции: ${stationsLabel})`))
  opts.onProgress?.(0, 0, 'Авторизация...')

  try {
    await stsLogin(undefined, login, password)
    log.push(logEntry('success', 'AUTH', 'Авторизация OK'))
  } catch (err) {
    log.push(logEntry('error', 'ERROR', `Авторизация: ${err instanceof Error ? err.message : err}`))
    addSyncLog(channel.id, log)
    updateChannel(channel.id, { status: 'error' })
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped: 0, duplicates, errors: 1, log }
  }

  for (const station of stations) {
    const stationId = station.code
    const systemId = station.systemId
    const stationTag = `${stationId}@sys${systemId}`

    let shifts: Awaited<ReturnType<typeof stsGetShifts>> = []
    try {
      shifts = await stsGetShifts(systemId, stationId)
      log.push(logEntry('info', 'LOAD', `Станция ${stationTag}: ${shifts.length} смен`))
    } catch (err) {
      log.push(logEntry('error', 'ERROR', `Станция ${stationTag}: ${err instanceof Error ? err.message : err}`))
      errors++
      continue
    }

    opts.onProgress?.(loaded, shifts.length, `Станция ${stationTag}: загрузка...`)

    for (const shift of shifts) {
      // Включаем system_id в fingerprint — иначе при работе с обеими
      // сетями одна и та же пара (station, shift) может перетереть запись.
      const fp = `shift|sys${systemId}|${stationId}|${shift.shift}`

      if (getLoadedDocs().some((d) => d.fingerprint === fp)) {
        duplicates++
        continue
      }

      try {
        const report = await stsGetShiftReport(stationId, shift.shift, systemId)
        const record = normalizeShift(stationId, shift.shift, shift.dt_open, shift.dt_close, report)

        const doc: LoadedDocument = {
          id: `shift-sys${systemId}-${stationId}-${shift.shift}`,
          channelId: channel.id,
          streamId: shiftStream.id,
          docType: 'shift_report',
          fingerprint: fp,
          title: `Смена №${shift.shift} — ${record.stationName}`,
          stationId,
          date: shift.dt_open,
          data: record,
          catalog: shiftStream.catalogTemplate
            .replace('{станция}', station.name ?? `АЗС-${stationId}`)
            .replace('{год}', new Date(shift.dt_open).getFullYear().toString())
            .replace('{месяц}', String(new Date(shift.dt_open).getMonth() + 1).padStart(2, '0')),
          loadedAt: new Date().toISOString(),
        }

        if (saveLoadedDoc(doc)) {
          loaded++
        } else {
          duplicates++
        }
      } catch (err) {
        log.push(logEntry('error', 'ERROR', `Смена ${shift.shift}: ${err instanceof Error ? err.message : err}`))
        errors++
      }

      opts.onProgress?.(loaded, shifts.length, `Смена №${shift.shift}`)
    }
  }

  const finishedAt = new Date().toISOString()
  log.push(logEntry('success', 'DONE', `Готово: ${loaded} загружено, ${duplicates} дубликатов, ${errors} ошибок`))

  addSyncLog(channel.id, log)
  updateChannel(channel.id, {
    status: errors > 0 ? 'error' : 'active',
    docsLoaded: (channel.docsLoaded || 0) + loaded,
    lastSync: finishedAt,
  })

  opts.onProgress?.(loaded, loaded, 'Готово')
  return { channelId: channel.id, startedAt, finishedAt, loaded, skipped: 0, duplicates, errors, log }
}

// ─── MSTO Sync ──────────────────────────────────────────────

/** Синхронизация MSTO — загрузка онлайн-заказов */
export async function syncMstoChannel(channel: Channel, opts: SyncOptions = {}): Promise<SyncResult> {
  const log: SyncLogEntry[] = []
  const startedAt = new Date().toISOString()
  let loaded = 0
  let duplicates = 0
  let errors = 0

  const primarySourceId = channel.sourceIds?.[0] ?? channel.sourceId ?? ''
  const source = getSource(primarySourceId)
  const conn = source?.connection ?? {}

  log.push(logEntry('info', 'SYNC', 'Загрузка онлайн-заказов MSTO'))
  opts.onProgress?.(0, 0, 'Авторизация MSTO...')

  try {
    await mstoLogin(undefined, conn.login, conn.password)
    log.push(logEntry('success', 'AUTH', 'MSTO авторизация OK'))
  } catch (err) {
    log.push(logEntry('error', 'ERROR', `MSTO авторизация: ${err instanceof Error ? err.message : err}`))
    addSyncLog(channel.id, log)
    updateChannel(channel.id, { status: 'error' })
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped: 0, duplicates, errors: 1, log }
  }

  const periodDays = channel.periodDays || 7
  const dateTo = new Date()
  const dateFrom = new Date(dateTo.getTime() - periodDays * 24 * 60 * 60 * 1000)

  const stationIds: number[] = (channel.config?.stationCodes ?? []).map(Number).filter(Boolean)

  opts.onProgress?.(0, 0, 'Загрузка транзакций...')

  try {
    const txs = await mstoGetTransactions(dateFrom, dateTo, stationIds.length ? stationIds : undefined, {
      url: undefined,
      login: conn.login,
      password: conn.password,
    })
    log.push(logEntry('info', 'LOAD', `MSTO: получено ${txs.length} транзакций`))

    const stream = (channel.streams ?? []).find((s) => s.docTypeId === 'msto_transactions' && s.enabled)

    for (const tx of txs) {
      const fp = `msto|${tx.id}|${tx.sessionId}`
      if (getLoadedDocs().some((d) => d.fingerprint === fp)) {
        duplicates++
        continue
      }

      const doc: LoadedDocument = {
        id: `msto-${tx.id}`,
        channelId: channel.id,
        streamId: stream?.id ?? '',
        docType: 'msto_transactions',
        fingerprint: fp,
        title: `${tx.tariff} — ${tx.service} ${tx.resultValue}л (${tx.servicePointName})`,
        stationId: tx.servicePointId,
        date: tx.dateTime,
        data: tx,
        catalog: stream?.catalogTemplate
          ?.replace('{объект}', tx.servicePointName || `SP-${tx.servicePointId}`)
          .replace('{год}', String(dateFrom.getFullYear()))
          .replace('{месяц}', String(dateFrom.getMonth() + 1).padStart(2, '0')) ?? '/msto/',
        loadedAt: new Date().toISOString(),
      }

      if (saveLoadedDoc(doc)) loaded++
      else duplicates++
    }

    try {
      const tariffs = await mstoGetTariffs({ url: undefined, login: conn.login, password: conn.password })
      log.push(logEntry('info', 'LOAD', `MSTO тарифы: ${tariffs.length}`))
    } catch { /* тарифы опциональны */ }

  } catch (err) {
    log.push(logEntry('error', 'ERROR', `MSTO транзакции: ${err instanceof Error ? err.message : err}`))
    errors++
  }

  const finishedAt = new Date().toISOString()
  log.push(logEntry('success', 'DONE', `MSTO: ${loaded} загружено, ${duplicates} дубликатов, ${errors} ошибок`))

  addSyncLog(channel.id, log)
  updateChannel(channel.id, {
    status: errors > 0 ? 'error' : 'active',
    docsLoaded: (channel.docsLoaded || 0) + loaded,
    lastSync: finishedAt,
  })

  opts.onProgress?.(loaded, loaded, 'Готово')
  return { channelId: channel.id, startedAt, finishedAt, loaded, skipped: 0, duplicates, errors, log }
}

// ─── TradeCorp Sync ─────────────────────────────────────────

/** Синхронизация TradeCorp — загрузка транзакций по корп. картам */
export async function syncTradecorpChannel(channel: Channel, opts: SyncOptions = {}): Promise<SyncResult> {
  const log: SyncLogEntry[] = []
  const startedAt = new Date().toISOString()
  let loaded = 0
  let duplicates = 0
  let errors = 0

  const primarySourceId = channel.sourceIds?.[0] ?? channel.sourceId ?? ''
  const source = getSource(primarySourceId)
  const conn = source?.connection ?? {}

  log.push(logEntry('info', 'SYNC', 'Загрузка транзакций TradeCorp'))
  opts.onProgress?.(0, 0, 'Авторизация TradeCorp...')

  try {
    await tradecorpLogin(undefined, conn.login, conn.password)
    log.push(logEntry('success', 'AUTH', 'TradeCorp авторизация OK'))
  } catch (err) {
    log.push(logEntry('error', 'ERROR', `TradeCorp авторизация: ${err instanceof Error ? err.message : err}`))
    addSyncLog(channel.id, log)
    updateChannel(channel.id, { status: 'error' })
    return { channelId: channel.id, startedAt, finishedAt: new Date().toISOString(), loaded, skipped: 0, duplicates, errors: 1, log }
  }

  const periodDays = channel.periodDays || 7
  const dateTo = new Date()
  const dateFrom = new Date(dateTo.getTime() - periodDays * 24 * 60 * 60 * 1000)

  const stationNumbers: number[] = (channel.config?.stationNumbers ?? channel.config?.stationCodes ?? []).map(Number).filter(Boolean)

  opts.onProgress?.(0, 0, 'Загрузка транзакций...')

  try {
    const txs = await tradecorpGetTransactions(dateFrom, dateTo, stationNumbers.length ? stationNumbers : undefined, {
      url: undefined,
      login: conn.login,
      password: conn.password,
      emitentId: conn.emitentId,
    })
    log.push(logEntry('info', 'LOAD', `TradeCorp: получено ${txs.length} транзакций`))

    const stream = (channel.streams ?? []).find((s) => s.docTypeId === 'corp_transactions' && s.enabled)

    for (const tx of txs) {
      const fp = `tradecorp|${tx.id}|${tx.date}|${tx.cardNumber}`
      if (getLoadedDocs().some((d) => d.fingerprint === fp)) {
        duplicates++
        continue
      }

      const doc: LoadedDocument = {
        id: `tc-${tx.id}`,
        channelId: channel.id,
        streamId: stream?.id ?? '',
        docType: 'corp_transactions',
        fingerprint: fp,
        title: `Карта ${tx.cardNumber} — ${tx.quantity}л (${tx.stationName})`,
        stationId: tx.stationNumber,
        date: tx.date,
        data: tx,
        catalog: stream?.catalogTemplate
          ?.replace('{объект}', tx.stationName || `Ст-${tx.stationNumber}`)
          .replace('{год}', String(dateFrom.getFullYear()))
          .replace('{месяц}', String(dateFrom.getMonth() + 1).padStart(2, '0')) ?? '/tradecorp/',
        loadedAt: new Date().toISOString(),
      }

      if (saveLoadedDoc(doc)) loaded++
      else duplicates++
    }
  } catch (err) {
    log.push(logEntry('error', 'ERROR', `TradeCorp транзакции: ${err instanceof Error ? err.message : err}`))
    errors++
  }

  const finishedAt = new Date().toISOString()
  log.push(logEntry('success', 'DONE', `TradeCorp: ${loaded} загружено, ${duplicates} дубликатов, ${errors} ошибок`))

  addSyncLog(channel.id, log)
  updateChannel(channel.id, {
    status: errors > 0 ? 'error' : 'active',
    docsLoaded: (channel.docsLoaded || 0) + loaded,
    lastSync: finishedAt,
  })

  opts.onProgress?.(loaded, loaded, 'Готово')
  return { channelId: channel.id, startedAt, finishedAt, loaded, skipped: 0, duplicates, errors, log }
}

// ─── Маршрутизатор синка по типу источника ──────────────────

/** Синхронизация — выбирает pipeline в зависимости от типа источника */
export async function syncChannel(channel: Channel, opts: SyncOptions = {}): Promise<SyncResult> {
  const primarySourceId = channel.sourceIds?.[0] ?? channel.sourceId ?? ''
  const source = getSource(primarySourceId)
  const sourceType = source?.type ?? 'rest'

  switch (sourceType) {
    case 'msto':
      return syncMstoChannel(channel, opts)
    case 'tradecorp':
      return syncTradecorpChannel(channel, opts)
    default:
      return syncRestChannel(channel, opts)
  }
}
