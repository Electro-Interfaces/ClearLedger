/** Public OAuth client for the docs trust boundary. Never writes Core auth storage. */
import { get, isApiEnabled, isDemoMode } from './apiClient'

export interface DocsMetadata {
  ready: boolean
  environment: 'unconfigured' | 'sandbox' | 'production'
  sandboxReady: boolean
  setupRequired: string[]
  clientId: string | null
  authorizationUrl: string
  tokenUrl: string
  revokeUrl: string
  redirectUri: string
  docsScopes: string[]
  coreUserId: string
}
export interface DocsSession { expiresAt: string; csrfToken: string; userId: string; clientId: string; companyId: string }
const PREFIX = '/api/developer/docs'
const TRANSACTION = 'elsy.docs.pkce'
let generation = 0
let docsToken: string | undefined
let callbackJob: { state: string; promise: Promise<DocsSession> } | undefined
let initialCallback = window.location.pathname.endsWith('/developer/api/callback') ? window.location.search : undefined
if (initialCallback !== undefined) history.replaceState(null, '', window.location.pathname)
export function docsCallbackInput(fallback: string) { return initialCallback ?? fallback }
export function cancelDocsRuntime() { generation++; docsToken = undefined; callbackJob = undefined }

export class DocsError extends Error {
  readonly status: number
  constructor(message: string, status = 0) { super(message); this.status = status; this.name = 'DocsError' }
}
const random = () => btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
const sameSpace = (value: string, path: string) => {
  const url = new URL(value)
  if (url.origin !== window.location.origin || url.pathname !== path || url.search || url.hash || url.username || url.password) throw new DocsError('Неверная настройка пространства')
  return url.href
}

export async function getDocsMetadata(signal?: AbortSignal): Promise<DocsMetadata> {
  if (!isApiEnabled() || isDemoMode()) throw new DocsError('Документация API недоступна в demo/offline', 503)
  // This one request belongs to Core. All OAuth/docs/product traffic below is separate.
  const data = await get<DocsMetadata>(`${PREFIX}/metadata`, undefined, { signal })
  sameSpace(data.authorizationUrl, '/api/oauth2/authorize'); sameSpace(data.tokenUrl, '/api/oauth2/token')
  sameSpace(data.revokeUrl, '/api/oauth2/revoke'); sameSpace(data.redirectUri, '/developer/api/callback')
  if (data.docsScopes.length !== 2 || !['openid', 'docs:read'].every((scope) => data.docsScopes.includes(scope))) throw new DocsError('Неверные права документации')
  return data
}

async function docsRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options })
  if (!response.ok) throw new DocsError(response.status === 401 || response.status === 403
    ? 'Доступ к документации завершён или отозван' : 'Документация API недоступна', response.status)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const getDocsSession = (signal?: AbortSignal) => docsRequest<DocsSession>(`${PREFIX}/session`, { signal })

export async function beginDocsLogin(metadata: DocsMetadata): Promise<void> {
  if (!metadata.ready || !metadata.clientId) throw new DocsError('Требуется настройка клиента документации', 503)
  const current = ++generation
  docsToken = undefined; callbackJob = undefined
  const verifier = random(), state = random(), nonce = random()
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  if (current !== generation) throw new DocsError('Запрос входа отменён')
  const challenge = btoa(String.fromCharCode(...new Uint8Array(hash))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  // Only the one-use PKCE transaction crosses a navigation. No codes/tokens/profile.
  sessionStorage.setItem(TRANSACTION, JSON.stringify({ verifier, state, nonce, generation: random(), expiresAt: Date.now() + 300_000 }))
  const url = new URL(sameSpace(metadata.authorizationUrl, '/api/oauth2/authorize'))
  url.search = new URLSearchParams({ response_type: 'code', client_id: metadata.clientId,
    redirect_uri: sameSpace(metadata.redirectUri, '/developer/api/callback'), scope: 'openid docs:read', state, nonce,
    code_challenge: challenge, code_challenge_method: 'S256', prompt: 'consent' }).toString()
  window.location.assign(url.href)
}

async function revoke(metadata: DocsMetadata, token?: string) {
  if (!token || !metadata.clientId) return
  await fetch(sameSpace(metadata.revokeUrl, '/api/oauth2/revoke'), { method: 'POST', credentials: 'omit', cache: 'no-store',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ client_id: metadata.clientId, token }) })
}

export function finishDocsLogin(search: string): Promise<DocsSession> {
  const query = new URLSearchParams(search)
  initialCallback = undefined
  history.replaceState(null, '', window.location.pathname)
  const state = query.get('state')
  if (state && callbackJob?.state === state) return callbackJob.promise // React StrictMode shares this one exchange.
  const promise = (async () => {
    const saved = sessionStorage.getItem(TRANSACTION)
    let pending: { state: string; verifier: string; nonce: string; generation: string; expiresAt: number } | null
    try { pending = saved ? JSON.parse(saved) : null } catch { sessionStorage.removeItem(TRANSACTION); throw new DocsError('Недействительное состояние входа') }
    if (pending && pending.expiresAt <= Date.now()) sessionStorage.removeItem(TRANSACTION)
    if (!pending || !state || query.getAll('state').length !== 1 || state !== pending.state || pending.expiresAt <= Date.now()
        || !pending.generation || !pending.nonce || typeof pending.verifier !== 'string' || pending.verifier.length < 43) throw new DocsError('Недействительный или просроченный возврат. Начните вход заново.')
    sessionStorage.removeItem(TRANSACTION)
    if (query.has('error') || query.getAll('code').length !== 1 || !query.get('code') || query.has('access_token') || query.has('id_token')) throw new DocsError('Согласие на документацию не получено')
    const current = ++generation
    const metadata = await getDocsMetadata()
    if (current !== generation) throw new DocsError('Запрос входа отменён')
    const response = await fetch(sameSpace(metadata.tokenUrl, '/api/oauth2/token'), { method: 'POST', credentials: 'omit', cache: 'no-store',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ grant_type: 'authorization_code',
        client_id: metadata.clientId ?? '', redirect_uri: metadata.redirectUri, code: query.get('code')!, code_verifier: pending.verifier }) })
    if (!response.ok) throw new DocsError('Код авторизации недействителен или уже использован', response.status)
    const tokens = await response.json() as { access_token: string; token_type: string; scope: string }
    // ID token is not used as browser identity. The server verifies access JWT and live Core grant.
    if (tokens.token_type?.toLowerCase() !== 'bearer' || !tokens.access_token
        || !['openid', 'docs:read'].every((scope) => tokens.scope?.split(' ').includes(scope))) {
      await revoke(metadata, tokens.access_token); throw new DocsError('Не получено право docs:read', 403)
    }
    if (current !== generation) { await revoke(metadata, tokens.access_token); throw new DocsError('Запрос входа отменён') }
    docsToken = tokens.access_token
    const session = await docsRequest<DocsSession>(`${PREFIX}/session`, { method: 'POST', headers: {
      Authorization: `Bearer ${docsToken}`, 'X-Docs-CSRF': 'bootstrap', 'Content-Type': 'application/json' }, body: '{}' })
    if (current !== generation) {
      try { await docsRequest(`${PREFIX}/session`, { method: 'DELETE', headers: { 'X-Docs-CSRF': session.csrfToken } }) }
      finally { await revoke(metadata, tokens.access_token) }
      throw new DocsError('Запрос входа отменён')
    }
    const currentSession = await getDocsSession()
    if (current !== generation) { await revoke(metadata, tokens.access_token); throw new DocsError('Запрос входа отменён') }
    if (currentSession.userId !== metadata.coreUserId) {
      await logoutDocs(currentSession, metadata); throw new DocsError('Учётная запись изменилась. Начните вход заново.')
    }
    return currentSession
  })()
  if (state) callbackJob = { state, promise }
  const release = () => { if (callbackJob?.promise === promise) callbackJob = undefined }
  void promise.then(release, release)
  return promise
}

export async function logoutDocs(session?: DocsSession, metadata?: DocsMetadata): Promise<void> {
  generation++; callbackJob = undefined; initialCallback = undefined; sessionStorage.removeItem(TRANSACTION)
  const token = docsToken; docsToken = undefined
  try {
    if (session) await docsRequest(`${PREFIX}/session`, { method: 'DELETE', headers: { 'X-Docs-CSRF': session.csrfToken } })
  } finally { if (metadata) await revoke(metadata, token) }
}
