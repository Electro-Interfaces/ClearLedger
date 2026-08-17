/**
 * HTTP-клиент для TradeLedger API.
 * Автоматическая подстановка JWT, обработка ошибок, refresh.
 *
 * Если VITE_API_URL не задан — API недоступен, используется localStorage.
 *
 * ВАЖНО для сборки образов: база — это ORIGIN, а не путь. Пути в коде уже содержат
 * `/api/...`, поэтому:
 *   * прод/контейнер: `VITE_API_URL=https://<домен>` (например https://rushydro.dataworker.ru);
 *   * `VITE_API_URL=/api` даёт `/api/api/...` — «Not Found» на каждом запросе;
 *   * пустое значение означает ДЕМО без бэкенда: `isApiEnabled()` становится false, и
 *     половина интерфейса (каталог приложений, нормализация, сверка) молча перестаёт
 *     запрашивать сервер. Именно так стол однажды оказался без плиток.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? ''
const TOKEN_KEY = 'clearledger-token'

/** API сконфигурирован? */
export const isApiEnabled = (): boolean => !!BASE_URL

// Активная компания из UI — уходит в заголовке X-Company-Id. Роутеры со скоупом
// «по юзеру» (fuel/store/…) раньше игнорировали выбор компании в шапке и всегда
// показывали дефолтную; теперь следуют выбору. Устанавливается из CompanyContext.
let activeCompanyId: string | null = null

/** Прокинуть активную компанию в HTTP-клиент (заголовок X-Company-Id). */
export function setApiCompany(id: string | null): void {
  activeCompanyId = id || null
}

// Активная ОРГАНИЗАЦИЯ (юрлицо внутри учёта клиента) — уходит заголовком
// X-Organization-Id. Компания решает, к чьему учёту есть доступ; организация — на
// какое юрлицо этого учёта человек сейчас смотрит. Пусто = все организации: сводная
// картина по клиенту нужна не реже, чем разрез по юрлицу.
const ORG_KEY = 'elsy.activeOrganization'
let activeOrganizationId: string | null = localStorage.getItem(ORG_KEY)

/** Прокинуть активную организацию в HTTP-клиент (заголовок X-Organization-Id). */
export function setApiOrganization(id: string | null): void {
  activeOrganizationId = id || null
  if (id) localStorage.setItem(ORG_KEY, id)
  else localStorage.removeItem(ORG_KEY)
}

/** Активная организация, выбранная в интерфейсе. */
export function getApiOrganization(): string | null {
  return activeOrganizationId
}

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
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Ошибка валидации Pydantic (422) с деталями по полям */
export class ApiValidationError extends ApiError {
  fieldErrors: Array<{ loc: string[]; msg: string; type: string }>
  constructor(detail: string, fieldErrors: Array<{ loc: string[]; msg: string; type: string }>) {
    super(422, detail)
    this.name = 'ApiValidationError'
    this.fieldErrors = fieldErrors
  }
}

/** Проверка: ошибка сети (нет подключения к серверу) */
export function isNetworkError(err: unknown): boolean {
  if (err instanceof TypeError && err.message.includes('fetch')) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  return false
}

/** Guard от множественных 401 редиректов (race condition при параллельных запросах) */
let isRedirecting = false

/** Страницы, доступные без сессии: увести отсюда на вход — значит сломать вход. */
const PUBLIC_PAGES = [
  '/login', '/invite/', '/reset-password/', '/showcase/', '/doc-share/', '/doc-verify/',
]
export function isPublicPage(pathname: string): boolean {
  const p = pathname.replace(/\/$/, '')
  return PUBLIC_PAGES.some((s) => p.endsWith(s.replace(/\/$/, '')) || p.includes(s))
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    let body: Record<string, unknown> | undefined
    try {
      body = await res.json()
      // Пустой detail оставлял экраны с сообщением «Не удалось …:» без причины —
      // ошибку было видно, а что именно сломалось, приходилось искать в логах.
      detail = (body?.detail as string) || JSON.stringify(body) || res.statusText
    } catch { /* ignore */ }

    if (res.status === 401 && !isRedirecting) {
      const base = import.meta.env.BASE_URL ?? '/'
      // На публичных страницах 401 от фоновых запросов — не «истёкшая сессия»: не шумим
      // и не редиректим (иначе фоновый 401 сбивает свежий вход). Приглашение и сброс
      // пароля открывают как раз те, у кого сессии нет или она протухла: `/auth/me`
      // отвечал 401, и форма улетала на логин через полторы секунды.
      if (!isPublicPage(window.location.pathname)) {
        isRedirecting = true
        clearToken()
        // Импортируем toast динамически чтобы избежать циклических зависимостей
        import('sonner').then(({ toast }) => {
          toast.error('Сессия истекла', { description: 'Войдите в систему снова' })
        })
        setTimeout(() => {
          window.location.href = `${base}login`
        }, 1500)
      }
    }

    if (res.status === 422 && body?.detail) {
      const fieldErrors = Array.isArray(body.detail)
        ? (body.detail as Array<{ loc: string[]; msg: string; type: string }>)
        : []
      const msg = fieldErrors.length > 0
        ? fieldErrors.map((e) => `${e.loc.join('.')}: ${e.msg}`).join('; ')
        : String(body.detail)
      throw new ApiValidationError(msg, fieldErrors)
    }

    if (res.status === 403) {
      throw new ApiError(403, 'Доступ запрещён. Проверьте права пользователя.')
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
  if (activeCompanyId) h['X-Company-Id'] = activeCompanyId
  if (activeOrganizationId) h['X-Organization-Id'] = activeOrganizationId
  return h
}

/** GET запрос */
export async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  // База обязательна: в контейнере VITE_API_URL пуст (API на том же origin), и без второго
  // аргумента `new URL('/api/…')` бросает «Invalid URL» — падали все GET с параметрами.
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
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

/** PUT запрос */
export async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PUT',
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
