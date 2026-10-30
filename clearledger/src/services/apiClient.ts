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

import { demoGet, demoPost, demoWrite } from '@/demo/demoApi'
import { safeBackTo } from '@/lib/safeBackTo'

const BASE_URL = import.meta.env.VITE_API_URL ?? ''
const TOKEN_KEY = 'clearledger-token'
const DEMO_KEY = 'tradeledger-demo'
const DEMO_PATH_PATTERN = /(^|\/)demo(\/|$)/

const demoParam = new URLSearchParams(window.location.search).get('demo')
if (demoParam === '1') sessionStorage.setItem(DEMO_KEY, '1')
if (demoParam === '0') sessionStorage.removeItem(DEMO_KEY)

/** Изолированный показ оригинального интерфейса на синтетических данных. */
export const isDemoPath = (): boolean => DEMO_PATH_PATTERN.test(window.location.pathname)
export const isDemoMode = (): boolean => {
  if (isDemoPath()) return true
  if (sessionStorage.getItem(DEMO_KEY) !== '1') return false
  // Флаг `?demo=1` живёт во вкладке, и человек, открывший демо-ссылку, а затем
  // вошедший в своё пространство в той же вкладке, продолжал смотреть синтетику
  // вместо собственных данных — молча, без единого признака. Настоящий вход
  // снимает демо: своих данных он ждёт, а не показа.
  if (localStorage.getItem(TOKEN_KEY)) {
    sessionStorage.removeItem(DEMO_KEY)
    return false
  }
  return true
}

/** API сконфигурирован? */
export const isApiEnabled = (): boolean => isDemoMode() || !!BASE_URL

// Активная компания из UI — уходит в заголовке X-Company-Id. Роутеры со скоупом
// «по юзеру» (fuel/store/…) раньше игнорировали выбор компании в шапке и всегда
// показывали дефолтную; теперь следуют выбору. Устанавливается из CompanyContext.
let activeCompanyId: string | null = null
// Только binary-запросы проверяют поколение. Оно замечает A→B→A и новый
// вход с тем же токеном; JSON-контракты и их жизненный цикл не меняются.
let binaryContextGeneration = 0

/** Прокинуть активную компанию в HTTP-клиент (заголовок X-Company-Id). */
export function setApiCompany(id: string | null): void {
  if (activeCompanyId !== (id || null)) binaryContextGeneration++
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
  if (activeOrganizationId !== (id || null)) binaryContextGeneration++
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
  return isDemoMode() ? 'demo-session' : localStorage.getItem(TOKEN_KEY)
}

/** Сохранить токен */
export function setToken(token: string): void {
  binaryContextGeneration++
  cancelSessionRedirect()
  localStorage.setItem(TOKEN_KEY, token)
}

/** Удалить токен */
export function clearToken(): void {
  binaryContextGeneration++
  localStorage.removeItem(TOKEN_KEY)
}

/**
 * Скачать файл выгрузки по адресу API.
 *
 * Имя берётся из ответа сервера, а не из аргумента: сервер собирает его по
 * RFC 5987 и умеет кириллицу («Реестр документов 20260831.xlsx»), а подставленное
 * здесь имя эту работу перечеркнёт и вернёт папку одинаковых файлов. Аргумент —
 * запасной вариант на случай, если заголовка нет.
 */
export async function downloadFile(path: string, fallbackName: string, options?: { signal?: AbortSignal }): Promise<void> {
  const { res, blob, guard } = await fetchBinary(path, options?.signal)
  const заголовок = res.headers.get('Content-Disposition') ?? ''
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(заголовок)
  const ascii = /filename="([^"]+)"/i.exec(заголовок)
  let имя = ascii?.[1] ?? fallbackName
  if (utf8) {
    try { имя = decodeURIComponent(utf8[1]) || имя } catch { /* повреждённый filename*: запасное имя */ }
  }

  guard()
  const url = URL.createObjectURL(blob)
  let a: HTMLAnchorElement | undefined
  try {
    guard()
    a = document.createElement('a')
    a.href = url
    a.download = имя
    guard()
    document.body.appendChild(a)
    guard()
    a.click()
  } finally {
    try { a?.remove() } finally { URL.revokeObjectURL(url) }
  }
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
let sessionRedirectTimer: ReturnType<typeof setTimeout> | undefined

function cancelSessionRedirect() {
  if (sessionRedirectTimer !== undefined) clearTimeout(sessionRedirectTimer)
  sessionRedirectTimer = undefined
  isRedirecting = false
}

function redirectExpiredSession() {
  sessionRedirectTimer = undefined
  // За время уведомления человек мог войти снова или уже попасть на login
  // со своим next. Старый таймер не имеет права выбросить новую сессию/intent.
  if (getToken() || isPublicPage(window.location.pathname)) { isRedirecting = false; return }
  const base = safeBackTo(import.meta.env.BASE_URL ?? '/').replace(/\/?$/, '/')
  const { pathname, search, hash } = window.location
  const path = base !== '/' && (pathname === base.slice(0, -1) || pathname.startsWith(base))
    ? `/${pathname.slice(base.length)}` : pathname
  const next = safeBackTo(`${path}${search}${hash}`)
  window.location.href = `${base}login?next=${encodeURIComponent(next)}`
}

/** Страницы, доступные без сессии: увести отсюда на вход — значит сломать вход. */
const PUBLIC_PAGES = [
  '/login', '/invite/', '/reset-password/', '/showcase/', '/demo/shop', '/doc-share/', '/doc-verify/',
  '/space-guest',
  '/developer/api/callback',
]
export function isPublicPage(pathname: string): boolean {
  const p = pathname.replace(/\/$/, '')
  return PUBLIC_PAGES.some((s) => p.endsWith(s.replace(/\/$/, '')) || p.includes(s))
}

async function handleResponseError(
  res: Response, sentAuthorization: string | undefined, signal?: AbortSignal, guard?: () => void,
): Promise<void> {
  if (!res.ok) {
    let detail = res.statusText
    let body: Record<string, unknown> | undefined
    try {
      body = await res.json()
      // Пустой detail оставлял экраны с сообщением «Не удалось …:» без причины —
      // ошибку было видно, а что именно сломалось, приходилось искать в логах.
      detail = (body?.detail as string) || JSON.stringify(body) || res.statusText
    } catch { /* ignore */ }

    // Для binary отмена/смена контекста важнее позднего HTTP-ответа,
    // особенно 401: прежний ответ не должен завершить новую сессию.
    guard?.()

    // Parsing the body is asynchronous too: compare the exact Bearer sent by
    // this request with the session that is current now, after that await.
    const currentToken = getToken()
    if (res.status === 401 && !isRedirecting && !signal?.aborted && currentToken
        && sentAuthorization === `Bearer ${currentToken}`) {
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
        sessionRedirectTimer = setTimeout(redirectExpiredSession, 1500)
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
      // Объяснение сервера важнее общей фразы: «этот разрез — для тех, кто
      // отвечает за чужую работу» говорит человеку, что делать, а «проверьте
      // права пользователя» отправляет его звонить. Общая фраза остаётся
      // запасной — на случай, когда сервер промолчал.
      throw new ApiError(403, detail && detail !== res.statusText
        ? detail
        : 'Доступ запрещён. Проверьте права пользователя.')
    }

    throw new ApiError(res.status, detail)
  }
}

async function handleResponse<T>(res: Response, sentAuthorization: string | undefined, signal?: AbortSignal): Promise<T> {
  if (!res.ok) await handleResponseError(res, sentAuthorization, signal)

  if (res.status === 204) return undefined as T
  const contentType = res.headers.get('content-type')?.toLowerCase() ?? ''
  if (!contentType.includes('application/json')) {
    throw new ApiError(502, 'Сервис вернул неожиданный ответ. Обновите страницу или повторите позже.')
  }
  try {
    return await res.json()
  } catch {
    throw new ApiError(502, 'Сервис вернул повреждённые данные. Обновите страницу или повторите позже.')
  }
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
export async function get<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  options?: { signal?: AbortSignal },
): Promise<T> {
  options?.signal?.throwIfAborted()
  if (isDemoMode()) return demoGet<T>(path, params)
  // База обязательна: в контейнере VITE_API_URL пуст (API на том же origin), и без второго
  // аргумента `new URL('/api/…')` бросает «Invalid URL» — падали все GET с параметрами.
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    }
  }
  const requestHeaders = headers()
  const res = await fetch(url.toString(), { headers: requestHeaders, signal: options?.signal })
  return handleResponse<T>(res, requestHeaders.Authorization, options?.signal)
}

/** POST запрос (JSON) */
export async function post<T>(path: string, body?: unknown): Promise<T> {
  if (isDemoMode()) return demoPost<T>(path)
  const requestHeaders = headers({ 'Content-Type': 'application/json' })
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: requestHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  return handleResponse<T>(res, requestHeaders.Authorization)
}

/** PATCH запрос */
export async function patch<T>(path: string, body: unknown): Promise<T> {
  if (isDemoMode()) return demoWrite<T>()
  const requestHeaders = headers({ 'Content-Type': 'application/json' })
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PATCH',
    headers: requestHeaders,
    body: JSON.stringify(body),
  })
  return handleResponse<T>(res, requestHeaders.Authorization)
}

/** PUT запрос */
export async function put<T>(path: string, body: unknown): Promise<T> {
  if (isDemoMode()) return demoWrite<T>()
  const requestHeaders = headers({ 'Content-Type': 'application/json' })
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PUT',
    headers: requestHeaders,
    body: JSON.stringify(body),
  })
  return handleResponse<T>(res, requestHeaders.Authorization)
}

/** DELETE запрос */
export async function del<T = void>(path: string): Promise<T> {
  if (isDemoMode()) return demoWrite<T>()
  const requestHeaders = headers()
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'DELETE',
    headers: requestHeaders,
  })
  return handleResponse<T>(res, requestHeaders.Authorization)
}

/** POST multipart (файлы) */
export async function upload<T>(
  path: string, formData: FormData,
  /**
   * Ход отправки, 0..1. Нужен файлам, которые едут минутами: видео на 60 МБ по
   * обычному каналу уходит полторы минуты, и всё это время `fetch` не сообщает
   * ничего. Человек видит замерший экран и решает, что загрузка не работает
   * (жалоба РусГидро 14.09.2026). С колбэком используется XHR — другого способа
   * узнать ход отправки в браузере нет, у `fetch` его не существует.
   */
  onProgress?: (доля: number) => void,
  /** Сохранить cross-origin cookies для явно запросившего их consumer. */
  options?: { credentials?: 'include' },
): Promise<T> {
  if (isDemoMode()) return demoWrite<T>()
  const requestHeaders = headers()
  if (!onProgress) {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: requestHeaders, // НЕ ставим Content-Type — browser сам добавит boundary
      body: formData,
      credentials: options?.credentials,
    })
    return handleResponse<T>(res, requestHeaders.Authorization)
  }
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE_URL}${path}`)
    if (options?.credentials === 'include') xhr.withCredentials = true
    for (const [k, v] of Object.entries(requestHeaders)) xhr.setRequestHeader(k, v)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      // Ответ разбираем тем же путём, что и `fetch`: коды, тексты ошибок и разбор
      // JSON обязаны совпадать, иначе у загрузки заведётся своя правда.
      const тело = new Response(xhr.response, {
        status: xhr.status,
        statusText: xhr.statusText,
        headers: { 'Content-Type': xhr.getResponseHeader('Content-Type') || 'application/json' },
      })
      handleResponse<T>(тело, requestHeaders.Authorization).then(resolve, reject)
    }
    xhr.onerror = () => reject(new ApiError(0, 'Не удалось связаться с сервером'))
    xhr.ontimeout = () => reject(new ApiError(0, 'Загрузка не уложилась во время ожидания'))
    xhr.send(formData)
  })
}

/** Общий binary transport: снимок заголовков и проверка каждого await. */
async function fetchBinary(path: string, signal?: AbortSignal) {
  signal?.throwIfAborted()
  if (isDemoMode()) return demoWrite<never>()
  const requestHeaders = headers()
  const generation = binaryContextGeneration
  const guard = () => {
    signal?.throwIfAborted()
    const currentHeaders = headers()
    if (generation !== binaryContextGeneration
        || requestHeaders.Authorization !== currentHeaders.Authorization
        || requestHeaders['X-Company-Id'] !== currentHeaders['X-Company-Id']
        || requestHeaders['X-Organization-Id'] !== currentHeaders['X-Organization-Id']) {
      throw new DOMException('Контекст выгрузки изменился', 'AbortError')
    }
  }
  const res = await fetch(`${BASE_URL}${path}`, { headers: requestHeaders, signal })
  guard()
  await handleResponseError(res, requestHeaders.Authorization, signal, guard)
  guard()
  const blob = await res.blob()
  guard()
  return { res, blob, guard }
}

/** Скачать файл (blob); прежний вызов без options остаётся совместимым. */
export async function downloadBlob(path: string, options?: { signal?: AbortSignal }): Promise<Blob> {
  const { blob, guard } = await fetchBinary(path, options?.signal)
  guard()
  return blob
}
