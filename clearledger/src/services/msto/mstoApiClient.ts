/**
 * HTTP-клиент для MSTO IntegratorService (онлайн-заказы агрегаторов).
 * API: http://46.229.214.21:3000
 * Аутентификация: JWT через POST /session.
 */

const TOKEN_KEY = 'gig-msto-token'
const TOKEN_EXPIRY_KEY = 'gig-msto-token-expiry'

// ─── Types ──────────────────────────────────────────────────

export interface MstoTransaction {
  id: number
  sessionId: string
  dateTime: string
  servicePointId: number
  servicePointName: string
  postNumber: number
  service: string
  tariff: string
  valueType: string
  value: number
  resultValue: number
  sum: number
  resultSum: number
  operationResult: 'success' | 'wait' | 'error' | 'cancel'
  discount: number
  agentInteresSum?: number
}

export interface MstoServicePoint {
  id: number
  name: string
}

export interface MstoTariff {
  id: number
  name: string
}

// ─── Token Management ───────────────────────────────────────

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
  // JWT ~1h, обновляем через 50 мин
  localStorage.setItem(TOKEN_EXPIRY_KEY, String(Date.now() + 50 * 60 * 1000))
}

export function clearMstoToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_EXPIRY_KEY)
}

// ─── Base URL ───────────────────────────────────────────────

function getMstoBaseUrl(overrideUrl?: string): string {
  if (overrideUrl) return overrideUrl
  if (import.meta.env.DEV) return '/msto'
  return 'http://46.229.214.21:3000'
}

// ─── HTTP helpers ───────────────────────────────────────────

async function fetchWithRetry(url: string, options: RequestInit, retries = 3): Promise<Response> {
  for (let i = 0; i < retries; i++) {
    try {
      return await fetch(url, { ...options, signal: AbortSignal.timeout(60000) })
    } catch (err) {
      if (i === retries - 1) throw err
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)))
    }
  }
  throw new Error('MSTO fetch failed after retries')
}

// ─── Auth ───────────────────────────────────────────────────

export async function mstoLogin(url?: string, login?: string, password?: string): Promise<string> {
  const baseUrl = getMstoBaseUrl(url)
  const resp = await fetchWithRetry(`${baseUrl}/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: login, password }),
  })

  if (!resp.ok) {
    throw new Error(`Ошибка авторизации MSTO: ${resp.status} ${resp.statusText}`)
  }

  const data = await resp.json()
  const token = data.token ?? data.accessToken ?? ''
  if (!token) throw new Error('MSTO: токен не получен')

  storeToken(token)
  return token
}

async function getToken(url?: string, login?: string, password?: string): Promise<string> {
  const stored = getStoredToken()
  if (stored) return stored
  return mstoLogin(url, login, password)
}

async function authFetch(path: string, url?: string, login?: string, password?: string): Promise<unknown> {
  const baseUrl = getMstoBaseUrl(url)
  let token = await getToken(url, login, password)

  let resp = await fetchWithRetry(`${baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })

  if (resp.status === 401) {
    clearMstoToken()
    token = await mstoLogin(url, login, password)
    resp = await fetchWithRetry(`${baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  }

  if (!resp.ok) {
    throw new Error(`MSTO API error: ${resp.status} ${resp.statusText} on ${path}`)
  }

  return resp.json()
}

// ─── Date helpers ───────────────────────────────────────────

function toMstoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// ─── API Methods ────────────────────────────────────────────

export async function mstoGetTransactions(
  dateFrom: Date,
  dateTo: Date,
  servicePointIds?: number[],
  conn?: { url?: string; login?: string; password?: string },
): Promise<MstoTransaction[]> {
  const params = new URLSearchParams({
    dateFrom: toMstoDate(dateFrom),
    dateTo: toMstoDate(dateTo),
    operationResult: 'success,wait',
    size: '2000',
  })
  if (servicePointIds?.length) {
    params.set('servicePointId', servicePointIds.join(','))
  }
  const data = await authFetch(`/private/transactions?${params}`, conn?.url, conn?.login, conn?.password) as { content?: MstoTransaction[] }
  return data.content ?? (Array.isArray(data) ? data as MstoTransaction[] : [])
}

export async function mstoGetServicePoints(
  conn?: { url?: string; login?: string; password?: string },
): Promise<MstoServicePoint[]> {
  return authFetch('/private/servicePoints', conn?.url, conn?.login, conn?.password) as Promise<MstoServicePoint[]>
}

export async function mstoGetTariffs(
  conn?: { url?: string; login?: string; password?: string },
): Promise<MstoTariff[]> {
  return authFetch('/private/tariffs', conn?.url, conn?.login, conn?.password) as Promise<MstoTariff[]>
}

// ─── Test Connection ────────────────────────────────────────

export async function mstoTestConnection(
  url: string,
  login: string,
  password: string,
): Promise<{ ok: boolean; error?: string; pointsCount?: number }> {
  try {
    await mstoLogin(url, login, password)
    const points = await mstoGetServicePoints({ url, login, password })
    return { ok: true, pointsCount: Array.isArray(points) ? points.length : 0 }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}
