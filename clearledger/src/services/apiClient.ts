/**
 * HTTP-клиент для ClearLedger API.
 * Автоматическая подстановка JWT, обработка ошибок, refresh.
 *
 * Если VITE_API_URL не задан — API недоступен, используется localStorage.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? ''
const TOKEN_KEY = 'clearledger-token'

/** API сконфигурирован? */
export const isApiEnabled = (): boolean => !!BASE_URL

/** Получить сохранённый токен */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

/** Сохранить токен */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

/** Удалить токен */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch { /* ignore */ }

    if (res.status === 401) {
      clearToken()
      const base = import.meta.env.BASE_URL ?? '/'
      window.location.href = `${base}login`
    }

    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return res.json()
}

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...extra }
  const token = getToken()
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

/** GET запрос */
export async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    }
  }
  const res = await fetch(url.toString(), { headers: headers() })
  return handleResponse<T>(res)
}

/** POST запрос (JSON) */
export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  return handleResponse<T>(res)
}

/** PATCH запрос */
export async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PATCH',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  return handleResponse<T>(res)
}

/** DELETE запрос */
export async function del<T = void>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'DELETE',
    headers: headers(),
  })
  return handleResponse<T>(res)
}

/** POST multipart (файлы) */
export async function upload<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: headers(), // НЕ ставим Content-Type — browser сам добавит boundary
    body: formData,
  })
  return handleResponse<T>(res)
}

/** Скачать файл (blob) */
export async function downloadBlob(path: string): Promise<Blob> {
  const res = await fetch(`${BASE_URL}${path}`, { headers: headers() })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.blob()
}
