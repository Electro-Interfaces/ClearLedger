/**
 * HTTP-клиент для STS API (pos.autooplata.ru/tms).
 * Аналог TL_ApiКлиент.bsl из расширения TradeLedger.
 *
 * В dev-режиме запросы идут через Vite proxy (/tms → pos.autooplata.ru).
 * В prod-режиме нужен свой proxy или прямой доступ.
 */

import type { StsShift, StsShiftReport, StsReceipt, StsPrice } from './types'
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
  // JWT expires in ~24h, we refresh after 20h
  localStorage.setItem(TOKEN_EXPIRY_KEY, String(Date.now() + 20 * 60 * 60 * 1000))
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

  const resp = await fetchWithRetry(`${baseUrl}/v1/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login: user, password: pass }),
  })

  if (!resp.ok) {
    throw new Error(`Ошибка авторизации STS: ${resp.status} ${resp.statusText}`)
  }

  const data = await resp.json()
  const token = typeof data === 'string' ? data : data.token
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

// ─── Test Connection ─────────────────────────────────────────

export async function stsTestConnection(
  url: string,
  login: string,
  password: string,
): Promise<{ ok: boolean; error?: string; shiftsCount?: number }> {
  try {
    const token = await stsLogin(url, login, password)
    // Попробуем получить список смен как проверку
    const settings = getSettings()
    const resp = await fetchWithRetry(`${url}/v1/shifts?system=${settings.stsSystemCode}`, {
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
