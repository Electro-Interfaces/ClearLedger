/** Пользовательское согласие OAuth. Транспорт и Core Bearer — только apiClient. */
import { ApiError, get, getToken, isApiEnabled, isDemoMode, post } from './apiClient'

export interface AuthorizationRequest {
  id: string
  clientName: string
  requestedScopes: { code: string; description: string }[]
  companies: { id: string; name: string; eligibleScopes: string[] }[]
  expiresAt: string
}

export type AuthorizationProblem = 'unavailable' | 'expired' | 'consumed' | 'not_found' | 'forbidden' | 'unauthenticated' | 'invalid' | 'redirect'
export class AuthorizationError extends Error {
  readonly kind: AuthorizationProblem
  constructor(kind: AuthorizationProblem) {
    super(kind)
    this.name = 'AuthorizationError'
    this.kind = kind
  }
}

export function authorizationProblem(error: unknown): AuthorizationProblem {
  if (error instanceof AuthorizationError) return error.kind
  if (error instanceof ApiError) {
    if (error.status === 401) return 'unauthenticated'
    if (error.status === 403) return 'forbidden'
    if (error.status === 410) return 'expired'
    if (error.status === 409) return 'consumed'
    if (error.status === 404) return 'not_found'
    if (error.status === 400 || error.status === 422) return 'invalid'
  }
  return 'unavailable'
}

export const AUTHORIZATION_PROBLEMS: Record<AuthorizationProblem, { title: string; description: string }> = {
  unavailable: { title: 'Подключение внешних приложений недоступно', description: 'Попробуйте позже или обратитесь к администратору пространства.' },
  expired: { title: 'Срок запроса истёк', description: 'Вернитесь в приложение и начните подключение заново.' },
  consumed: { title: 'Запрос уже обработан', description: 'Начните подключение заново в приложении, если ему нужен новый доступ.' },
  not_found: { title: 'Запрос не найден или недоступен', description: 'Проверьте ссылку или начните подключение заново в приложении.' },
  forbidden: { title: 'Доступ запрещён или отозван', description: 'Вашей учётной записи недоступно это подключение. Обратитесь к администратору.' },
  unauthenticated: { title: 'Необходимо войти снова', description: 'Войдите в пространство, чтобы просмотреть запрос согласия.' },
  invalid: { title: 'Некорректный запрос подключения', description: 'Откройте новую ссылку из приложения и выберите доступные действия.' },
  redirect: { title: 'Не удалось безопасно вернуться в приложение', description: 'Сервер вернул неподдерживаемый адрес. Не повторяйте согласие; обратитесь к администратору.' },
}

function containsControlCharacters(value: string): boolean {
  return Array.from(value).some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
}

export function authorizationRequestId(search: string): string | null {
  const ids = new URLSearchParams(search).getAll('requestId')
  const id = ids[0]
  return ids.length === 1 && id && id.length <= 1024 && !containsControlCharacters(id) ? id : null
}

function requireRealSession() {
  if (!isApiEnabled() || isDemoMode()) throw new AuthorizationError('unavailable')
  const token = getToken()
  if (!token || token === 'demo-session') throw new AuthorizationError('unauthenticated')
}

function requestPath(id: string) {
  if (!id || id.length > 1024 || containsControlCharacters(id)) throw new AuthorizationError('invalid')
  return `/api/developer/authorization-requests/${encodeURIComponent(id)}`
}

/** Только пересечение запрошенных действий и разрешений выбранной компании. */
export function eligibleAuthorizationScopes(request: AuthorizationRequest, companyId: string): string[] {
  const company = request.companies.find((item) => item.id === companyId)
  const eligible = new Set(company?.eligibleScopes ?? [])
  return request.requestedScopes.map((scope) => scope.code).filter((code) => eligible.has(code))
}

/** Сервер проверяет registration redirect URI; клиент дополнительно ограничивает схему. */
export function authorizationRedirectUrl(value: unknown, development = import.meta.env.DEV): string {
  if (typeof value !== 'string' || !value || value !== value.trim() || containsControlCharacters(value)
      || value.includes(' ') || value.includes('\\')) {
    throw new AuthorizationError('redirect')
  }
  let url: URL
  try { url = new URL(value) } catch { throw new AuthorizationError('redirect') }
  const localHttp = development && url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if ((url.protocol !== 'https:' && !localHttp) || url.username || url.password) throw new AuthorizationError('redirect')
  return url.href
}

function readRequest(value: unknown, requestId: string): AuthorizationRequest {
  // Не даём некорректному ответу превратиться в пустой успешный экран согласия.
  if (!value || typeof value !== 'object') throw new AuthorizationError('unavailable')
  const item = value as Partial<AuthorizationRequest>
  if (item.id !== requestId || typeof item.clientName !== 'string' || !item.clientName.trim()
      || typeof item.expiresAt !== 'string' || !Number.isFinite(Date.parse(item.expiresAt))
      || !Array.isArray(item.requestedScopes) || !Array.isArray(item.companies)
      || !item.requestedScopes.every((scope) => scope && typeof scope.code === 'string' && scope.code
        && typeof scope.description === 'string')
      || !item.companies.every((company) => company && typeof company.id === 'string' && company.id
        && typeof company.name === 'string' && Array.isArray(company.eligibleScopes)
        && company.eligibleScopes.every((scope) => typeof scope === 'string'))
      || new Set(item.requestedScopes.map((scope) => scope.code)).size !== item.requestedScopes.length
      || new Set(item.companies.map((company) => company.id)).size !== item.companies.length) {
    throw new AuthorizationError('unavailable')
  }
  return item as AuthorizationRequest
}

export async function getAuthorizationRequest(id: string, signal?: AbortSignal): Promise<AuthorizationRequest> {
  requireRealSession()
  return readRequest(await get<unknown>(requestPath(id), undefined, { signal }), id)
}

export async function approveAuthorizationRequest(request: AuthorizationRequest, companyId: string, scopes: string[]): Promise<string> {
  requireRealSession()
  if (Date.parse(request.expiresAt) <= Date.now()) throw new AuthorizationError('expired')
  const eligible = new Set(eligibleAuthorizationScopes(request, companyId))
  if (!request.companies.some((company) => company.id === companyId) || !scopes.length
      || new Set(scopes).size !== scopes.length || scopes.some((scope) => !eligible.has(scope))
      || (request.requestedScopes.some((scope) => scope.code === 'openid') && !scopes.includes('openid'))) {
    throw new AuthorizationError('invalid')
  }
  const result = await post<{ redirectUrl: string }>(`${requestPath(request.id)}/approve`, { companyId, scopes })
  return authorizationRedirectUrl(result?.redirectUrl)
}

export async function denyAuthorizationRequest(id: string): Promise<string> {
  requireRealSession()
  const result = await post<{ redirectUrl: string }>(`${requestPath(id)}/deny`)
  return authorizationRedirectUrl(result?.redirectUrl)
}
