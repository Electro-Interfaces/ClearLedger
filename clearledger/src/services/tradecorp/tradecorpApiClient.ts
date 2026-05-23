/**
 * HTTP-клиент для TradeCorp API (корпоративные карты).
 * API: https://api.autooplata.ru
 * Аутентификация: JSON-RPC 2.0 login → Bearer token.
 */

const TOKEN_KEY = 'gig-tradecorp-token'
const TOKEN_EXPIRY_KEY = 'gig-tradecorp-token-expiry'

// ─── Types ──────────────────────────────────────────────────

export interface TradecorpTransaction {
  id: number
  date: string
  cardNumber: string
  cardId: number
  stationId: number
  stationNumber: number
  stationName: string
  operationName: string
  /** Литры */
  quantity: number
  /** Рубли */
  cost: number
  /** Цена за литр */
  price: number
  cheque: {
    productName: string
    quantity: number
    cost: number
    price: number
  }[]
}

export interface TradecorpSummary {
  stationNumber: number
  stationName: string
  totalQuantity: number
  totalCost: number
  transactionsCount: number
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
  // Token ~1h, обновляем через 50 мин
  localStorage.setItem(TOKEN_EXPIRY_KEY, String(Date.now() + 50 * 60 * 1000))
}

export function clearTradecorpToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_EXPIRY_KEY)
}

// ─── Base URL ───────────────────────────────────────────────

function getTradecorpBaseUrl(overrideUrl?: string): string {
  if (overrideUrl) return overrideUrl
  if (import.meta.env.DEV) return '/tradecorp'
  return 'https://api.autooplata.ru'
}

// ─── HTTP helpers ───────────────────────────────────────────

async function fetchWithRetry(url: string, options: RequestInit, retries = 3): Promise<Response> {
  for (let i = 0; i < retries; i++) {
    try {
      return await fetch(url, { ...options, signal: AbortSignal.timeout(30000) })
    } catch (err) {
      if (i === retries - 1) throw err
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)))
    }
  }
  throw new Error('TradeCorp fetch failed after retries')
}

// ─── Auth (JSON-RPC 2.0) ───────────────────────────────────

export async function tradecorpLogin(url?: string, login?: string, password?: string): Promise<string> {
  const baseUrl = getTradecorpBaseUrl(url)
  const resp = await fetchWithRetry(`${baseUrl}/v2`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'login',
      params: { login, password },
    }),
  })

  if (!resp.ok) {
    throw new Error(`Ошибка авторизации TradeCorp: ${resp.status} ${resp.statusText}`)
  }

  const data = await resp.json()
  if (data.error) {
    throw new Error(`TradeCorp login: ${data.error.message ?? JSON.stringify(data.error)}`)
  }
  const token = data.result?.token ?? data.result ?? ''
  if (!token) throw new Error('TradeCorp: токен не получен')

  storeToken(token)
  return token
}

async function getToken(url?: string, login?: string, password?: string): Promise<string> {
  const stored = getStoredToken()
  if (stored) return stored
  return tradecorpLogin(url, login, password)
}

async function authPost(
  body: unknown,
  url?: string,
  login?: string,
  password?: string,
): Promise<unknown> {
  const baseUrl = getTradecorpBaseUrl(url)
  let token = await getToken(url, login, password)

  let resp = await fetchWithRetry(`${baseUrl}/v1`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })

  if (resp.status === 401) {
    clearTradecorpToken()
    token = await tradecorpLogin(url, login, password)
    resp = await fetchWithRetry(`${baseUrl}/v1`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    })
  }

  if (!resp.ok) {
    throw new Error(`TradeCorp API error: ${resp.status} ${resp.statusText}`)
  }

  const data = await resp.json()
  if (data.error) {
    throw new Error(`TradeCorp: ${data.error.message ?? JSON.stringify(data.error)}`)
  }
  return data.result ?? data
}

// ─── Date helpers ───────────────────────────────────────────

function toTcDate(d: Date): string {
  return d.toISOString().replace('T', ' ').slice(0, 19)
}

// ─── API Methods ────────────────────────────────────────────

/** Операции: 603=заправка, 614=возврат, 504-511=операции по счёту */
const DEFAULT_OPERATIONS = [603, 614, 504, 505, 508, 511]

export async function tradecorpGetTransactions(
  dateFrom: Date,
  dateTo: Date,
  stationNumbers?: number[],
  conn?: { url?: string; login?: string; password?: string; emitentId?: string },
): Promise<TradecorpTransaction[]> {
  const filter: Record<string, unknown> = {
    operation: [{ equal: DEFAULT_OPERATIONS }],
    date: [{ more: [toTcDate(dateFrom)], less: [toTcDate(dateTo)] }],
    card: { id: [{ unequal: [null] }] },
  }
  if (stationNumbers?.length) {
    filter.station = { number: [{ equal: stationNumbers }] }
  }

  const raw = await authPost(
    {
      jsonrpc: '2.0',
      id: 2,
      method: 'transactions_get',
      params: {
        emitent_id: Number(conn?.emitentId) || 15,
        filter,
        limit: 5000,
        offset: 0,
      },
    },
    conn?.url,
    conn?.login,
    conn?.password,
  ) as { transactions?: unknown[] } | unknown[]

  const txs = Array.isArray(raw) ? raw : (raw as { transactions?: unknown[] }).transactions ?? []

  return txs.map((t: any) => ({
    id: t.id,
    date: t.date,
    cardNumber: t.card_number ?? t.cardNumber ?? '',
    cardId: t.card_id ?? t.cardId ?? 0,
    stationId: t.station_id ?? t.stationId ?? 0,
    stationNumber: t.station_number ?? t.stationNumber ?? 0,
    stationName: t.station_name ?? t.stationName ?? '',
    operationName: t.operation_name ?? t.operationName ?? '',
    quantity: (t.quantity ?? 0) / 100,
    cost: (t.cost ?? 0) / 100,
    price: t.price ?? 0,
    cheque: (t.cheque ?? []).map((c: any) => ({
      productName: c.product_name ?? c.productName ?? '',
      quantity: (c.quantity ?? 0) / 100,
      cost: (c.cost ?? 0) / 100,
      price: c.price ?? 0,
    })),
  }))
}

export async function tradecorpGetSummary(
  dateFrom: Date,
  dateTo: Date,
  stationNumbers?: number[],
  conn?: { url?: string; login?: string; password?: string; emitentId?: string },
): Promise<TradecorpSummary[]> {
  const txs = await tradecorpGetTransactions(dateFrom, dateTo, stationNumbers, conn)

  const map = new Map<number, TradecorpSummary>()
  for (const t of txs) {
    const key = t.stationNumber
    if (!map.has(key)) {
      map.set(key, { stationNumber: key, stationName: t.stationName, totalQuantity: 0, totalCost: 0, transactionsCount: 0 })
    }
    const s = map.get(key)!
    s.totalQuantity += t.quantity
    s.totalCost += t.cost
    s.transactionsCount++
  }

  return [...map.values()]
}

// ─── Test Connection ────────────────────────────────────────

export async function tradecorpTestConnection(
  url: string,
  login: string,
  password: string,
  emitentId: string,
): Promise<{ ok: boolean; error?: string; txCount?: number }> {
  try {
    await tradecorpLogin(url, login, password)
    const now = new Date()
    const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
    const txs = await tradecorpGetTransactions(weekAgo, now, undefined, { url, login, password, emitentId })
    return { ok: true, txCount: txs.length }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) }
  }
}
