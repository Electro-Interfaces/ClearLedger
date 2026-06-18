/**
 * HTTP-клиент для STS API (pos.autooplata.ru/tms).
 * Аналог TL_ApiКлиент.bsl из расширения TradeLedger.
 *
 * В dev-режиме запросы идут через Vite proxy (/tms → pos.autooplata.ru).
 * В prod-режиме нужен свой proxy или прямой доступ.
 */

import type { StsShift, StsShiftReport, StsReceipt, StsPrice, StsTransaction } from './types'
import { getSettings } from '../settingsService'

const TOKEN_KEY = 'gig-sts-token'
const TOKEN_EXPIRY_KEY = 'gig-sts-token-expiry'

// ─── Token Management ────────────────────────────────────────

function getStoredToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY)
  const expiry = localStorage.getItem(TOKEN_EXPIRY_KEY)
  if (!token || !expiry) return null
  if (Date.now() > Number(expiry)) {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(TOKEN_EXPIRY_KEY)
    return null
  }
  return token
}

function storeToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
  // JWT expires in ~20 min, refresh after 18 min
  localStorage.setItem(TOKEN_EXPIRY_KEY, String(Date.now() + 18 * 60 * 1000))
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_EXPIRY_KEY)
}

// ─── Base URL ────────────────────────────────────────────────

function getBaseUrl(): string {
  const settings = getSettings()
  // В dev-режиме используем Vite proxy
  if (import.meta.env.DEV) {
    return '/tms'
  }
  return settings.stsApiUrl
}

// ─── HTTP helpers ────────────────────────────────────────────

async function fetchWithRetry(url: string, options: RequestInit, retries = 3): Promise<Response> {
  for (let i = 0; i < retries; i++) {
    try {
      const resp = await fetch(url, { ...options, signal: AbortSignal.timeout(30000) })
      return resp
    } catch (err) {
      if (i === retries - 1) throw err
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)))
    }
  }
  throw new Error('Fetch failed after retries')
}

// ─── Auth ────────────────────────────────────────────────────

export async function stsLogin(url?: string, login?: string, password?: string): Promise<string> {
  const settings = getSettings()
  const baseUrl = url ?? getBaseUrl()
  const user = login ?? settings.stsLogin
  const pass = password ?? settings.stsPassword

  // STS API v2: POST /v2/login с полем user как объект {id, name}
  const resp = await fetchWithRetry(`${baseUrl}/v2/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      login: user,
      password: pass,
      user: {
        id: '00000000-0000-0000-0000-000000000000',
        name: 'System',
      },
    }),
  })

  if (!resp.ok) {
    throw new Error(`Ошибка авторизации STS: ${resp.status} ${resp.statusText}`)
  }

  // STS может вернуть токен как голую строку или JSON {token: "..."}
  const text = await resp.text()
  let token = text.trim().replace(/^"|"$/g, '')
  if (token.startsWith('{')) {
    try {
      const obj = JSON.parse(token)
      token = obj.token ?? ''
    } catch { /* use as-is */ }
  }
  if (!token) throw new Error('Токен не получен')

  storeToken(token)
  return token
}

async function getToken(): Promise<string> {
  const stored = getStoredToken()
  if (stored) return stored
  return stsLogin()
}

async function authFetch(path: string): Promise<unknown> {
  const baseUrl = getBaseUrl()
  let token = await getToken()

  let resp = await fetchWithRetry(`${baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })

  // Auto re-login on 401
  if (resp.status === 401) {
    clearToken()
    token = await stsLogin()
    resp = await fetchWithRetry(`${baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  }

  if (!resp.ok) {
    throw new Error(`STS API error: ${resp.status} ${resp.statusText} on ${path}`)
  }

  return resp.json()
}

// ─── API Methods ─────────────────────────────────────────────

export async function stsGetShifts(system?: number, station?: number): Promise<StsShift[]> {
  const settings = getSettings()
  const sys = system ?? settings.stsSystemCode
  const params = new URLSearchParams({ system: String(sys) })
  if (station != null) params.set('station', String(station))
  return authFetch(`/v1/shifts?${params}`) as Promise<StsShift[]>
}

/** Торговая точка STS (GET /v1/points) — авто-discovery станций сети. */
export interface StsPoint {
  id?: number
  number?: number
  name?: string
  address?: string
}

/** Список торговых точек системы (GET /v1/points?system=). */
export async function stsGetPoints(system?: number): Promise<StsPoint[]> {
  const settings = getSettings()
  const sys = system ?? settings.stsSystemCode
  return authFetch(`/v1/points?system=${sys}`) as Promise<StsPoint[]>
}

export async function stsGetShiftReport(station: number, shift: number, system?: number): Promise<StsShiftReport> {
  const settings = getSettings()
  const sys = system ?? settings.stsSystemCode
  const params = new URLSearchParams({
    system: String(sys),
    station: String(station),
    shift: String(shift),
  })
  return authFetch(`/v1/report/shift_report?${params}`) as Promise<StsShiftReport>
}

export async function stsGetReceipts(station: number, shift: number, system?: number): Promise<StsReceipt[]> {
  const settings = getSettings()
  const sys = system ?? settings.stsSystemCode
  const params = new URLSearchParams({
    system: String(sys),
    station: String(station),
    shift: String(shift),
  })
  return authFetch(`/v1/report/receipts?${params}`) as Promise<StsReceipt[]>
}

export async function stsGetPrices(station: number, system?: number): Promise<StsPrice[]> {
  const settings = getSettings()
  const sys = system ?? settings.stsSystemCode
  const params = new URLSearchParams({
    system: String(sys),
    station: String(station),
  })
  return authFetch(`/v1/prices?${params}`) as Promise<StsPrice[]>
}

/**
 * Пооперационный факт отпуска на ТРК — STS `/v2/transactions`.
 *
 * Запрос (как ходит TradeFrame STSApiService): `system` + `dt_beg`/`dt_end`
 * (границы суток `YYYY-MM-DD HH:mm:ss`). Параметр `station` опционален —
 * без него API отдаёт операции по всем станциям системы.
 *
 * Ответ STS: `[{ system, number, total, items: [...] }]`. Здесь массив
 * «расплющивается» в плоский список операций с добавленным `stationNumber`
 * (взятым из обёртки `number`). Никакой фильтрации/нормализации тут нет —
 * это делает вызывающий dataFetcher (фильтр по корп.картам/online, датам).
 *
 * @param dateFrom — YYYY-MM-DD (начало периода)
 * @param dateTo   — YYYY-MM-DD (конец периода, включительно)
 * @param station  — номер станции (опционально; без него — все станции)
 * @param system   — код системы STS (по умолчанию из настроек)
 */
export async function stsGetTransactions(
  dateFrom: string,
  dateTo: string,
  station?: number,
  system?: number,
): Promise<StsTransaction[]> {
  const settings = getSettings()
  const sys = system ?? settings.stsSystemCode

  const params = new URLSearchParams({ system: String(sys) })
  // STS ожидает границы суток в формате "YYYY-MM-DD HH:mm:ss"
  if (dateFrom) params.set('dt_beg', `${dateFrom} 00:00:00`)
  if (dateTo) params.set('dt_end', `${dateTo} 23:59:59`)
  if (station != null) params.set('station', String(station))

  const data = await authFetch(`/v2/transactions?${params}`)

  // Ответ: [{ system, number, total, items: [...] }]
  const flat: StsTransaction[] = []
  if (Array.isArray(data)) {
    for (const stationBlock of data as Array<{ number?: number; items?: unknown[] }>) {
      const items = Array.isArray(stationBlock?.items) ? stationBlock.items : []
      for (const tx of items) {
        flat.push({
          ...(tx as Record<string, unknown>),
          stationNumber: (tx as { stationNumber?: number }).stationNumber ?? stationBlock.number ?? 0,
        } as StsTransaction)
      }
    }
  }
  return flat
}

// ─── Discover stations ──────────────────────────────────────
//
// У STS API нет endpoint списка станций — но `stsGetShifts(system, station)`
// возвращает массив смен только для существующих станций (и пустой/4xx для
// несуществующих). Дёргая пары (system_id, station) из пула, можно
// собрать актуальный список «живых» торговых точек.

export interface StsDiscoveredStation {
  system: number
  station: number
  /** Смен найдено за всё время по этому коду */
  shiftsCount: number
  /** Последняя смена — её dt_open для сортировки активности */
  lastShiftAt: string | null
  /** Активна (есть смены за последние 90 дней) */
  recentActive: boolean
}

/**
 * Сканировать пул кодов на конкретной системе STS и вернуть существующие
 * станции с количеством смен и временем последней смены.
 *
 * `concurrency` — сколько параллельных запросов держим (по умолчанию 6).
 * `onProgress` — колбэк прогресса (доля 0..1) для UI.
 */
export async function stsDiscoverStations(
  system: number,
  stationCodes: number[],
  options: {
    concurrency?: number
    onProgress?: (done: number, total: number) => void
  } = {},
): Promise<StsDiscoveredStation[]> {
  const concurrency = options.concurrency ?? 6
  const total = stationCodes.length
  let done = 0

  const results: StsDiscoveredStation[] = []
  const ninetyDaysAgo = Date.now() - 90 * 24 * 60 * 60 * 1000

  // Поллер чтобы не упереться в rate-limit STS
  async function check(code: number): Promise<StsDiscoveredStation | null> {
    try {
      const shifts = await stsGetShifts(system, code)
      if (!Array.isArray(shifts) || shifts.length === 0) return null
      // Последняя по dt_open
      let lastDt: string | null = null
      for (const s of shifts) {
        if (s.dt_open && (!lastDt || s.dt_open > lastDt)) lastDt = s.dt_open
      }
      const recentActive = lastDt ? new Date(lastDt).getTime() >= ninetyDaysAgo : false
      return {
        system,
        station: code,
        shiftsCount: shifts.length,
        lastShiftAt: lastDt,
        recentActive,
      }
    } catch {
      return null
    } finally {
      done += 1
      options.onProgress?.(done, total)
    }
  }

  // Простой пул: запускаем concurrency задач, по мере завершения добавляем
  const queue = [...stationCodes]
  const workers: Promise<void>[] = []
  for (let i = 0; i < Math.min(concurrency, queue.length); i++) {
    workers.push(
      (async () => {
        while (queue.length > 0) {
          const code = queue.shift()!
          const r = await check(code)
          if (r) results.push(r)
        }
      })(),
    )
  }
  await Promise.all(workers)

  // Сортировка по коду станции для предсказуемого порядка
  results.sort((a, b) => a.station - b.station)
  return results
}

// ─── Test Connection ─────────────────────────────────────────

export async function stsTestConnection(
  _url: string,
  login: string,
  password: string,
): Promise<{ ok: boolean; error?: string; shiftsCount?: number }> {
  try {
    // Всегда используем getBaseUrl() (proxy в dev, полный URL в prod)
    const token = await stsLogin(undefined, login, password)
    const settings = getSettings()
    const baseUrl = getBaseUrl()
    const resp = await fetchWithRetry(`${baseUrl}/v1/shifts?system=${settings.stsSystemCode}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!resp.ok) {
      return { ok: false, error: `API вернул ${resp.status}` }
    }
    const shifts = await resp.json() as StsShift[]
    return { ok: true, shiftsCount: shifts.length }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}
