// Приложение «Телефония»: экраны администратора узла заказчика поверх API узла.
//
// Узел стоит у заказчика, и его данные (номера, записи, расшифровки) Ядро не видит:
// браузер ходит в узел напрямую через кромку стека — `/voice/api/v1/…`, nginx срезает
// `/voice` и проксирует на узел. Пропуск — короткий токен Ядра `aud=voice`, узел сверяет
// его по JWKS своего пространства. Контракт — ContactHub/docs/node-admin-api.yaml.
//
// Общий `apiClient` здесь не подходит: на 401 он разлогинивает человека из пространства.
// Узел, не принявший токен, — это не истёкшая сессия Ядра, а повод выпустить новый токен.
import { get as coreGet } from './apiClient'

const CORE = import.meta.env.VITE_API_URL ?? ''
/** Адрес API узла. На стенде задаётся прямо (`VITE_VOICE_API_URL`), в пространстве — тот же origin. */
const BASE: string = import.meta.env.VITE_VOICE_API_URL || `${CORE}/voice/api/v1`

// ——— Токен ———

interface Пропуск { token: string; exp: number }

const пропуски = new Map<string, Пропуск>()
const выдачи = new Map<string, Promise<Пропуск>>()

/**
 * Выпустить токен `aud=voice` для компании. В пространстве — ручка Ядра; на стенде без
 * Ядра — местный издатель токенов (`VITE_VOICE_DEV_TOKEN_URL`, только в dev-сборке).
 */
async function выпустить(companyId: string): Promise<Пропуск> {
  const dev = import.meta.env.DEV ? import.meta.env.VITE_VOICE_DEV_TOKEN_URL as string | undefined : undefined
  if (dev) {
    const res = await fetch(`${dev}?cid=${encodeURIComponent(companyId)}`)
    if (!res.ok) throw new VoiceError(res.status, 'dev_token', 'Местный издатель токенов не ответил')
    const r = await res.json() as { token: string; expires_in: number }
    return { token: r.token, exp: Date.now() + r.expires_in * 1000 }
  }
  const r = await coreGet<{ token: string; expires_in: number }>('/api/sso/token',
    { app: 'voice', company_id: companyId })
  return { token: r.token, exp: Date.now() + r.expires_in * 1000 }
}

/** Токен для узла: из памяти, пока до конца срока больше минуты, иначе новый. */
export async function voiceToken(companyId: string): Promise<Пропуск> {
  const п = пропуски.get(companyId)
  if (п && п.exp - Date.now() > 60_000) return п
  let в = выдачи.get(companyId)
  if (!в) {
    в = выпустить(companyId).finally(() => выдачи.delete(companyId))
    выдачи.set(companyId, в)
  }
  const н = await в
  пропуски.set(companyId, н)
  return н
}

function забыть(companyId: string) {
  пропуски.delete(companyId)
}

// ——— Ошибки ———

/** Ошибка узла: RFC 9457 (`status`, `error`, `detail`), в `detail` ПДн нет. */
export class VoiceError extends Error {
  status: number
  code: string
  issues?: Issue[]
  constructor(status: number, code: string, message: string, issues?: Issue[]) {
    super(message)
    this.status = status
    this.code = code
    this.issues = issues
  }
}

/** Код ошибки узла словами: администратор не обязан знать `address_forbidden`. */
const ОШИБКИ: Record<string, string> = {
  invalid_token: 'Узел не принял вход пространства: подпись или срок токена не прошли проверку',
  address_forbidden: 'Узел не принимает запросы с этого адреса: проверьте маршрут /voice в стеке',
  reason_required: 'Нужна причина: доступ к номеру, записи и расшифровке пишется в журнал',
  number_purged: 'Номер уже заменён хешем по сроку хранения',
  recording_purged: 'Запись удалена по сроку хранения',
  too_many_streams: 'К узлу открыто слишком много экранов «Сейчас», закройте лишние вкладки',
  draft_exists: 'Черновик уже есть: его начал другой администратор или вы в другой вкладке',
  draft_outdated: 'Пока шла правка, действующая версия сменилась: начните черновик заново',
  not_validated: 'Сначала проверьте черновик',
  config_invalid: 'Проверка при применении нашла ошибки, работает прежняя версия',
  callback_busy: 'Задача уже у оператора: идёт набор или разговор',
  callback_not_scheduled: 'Задача уже закрыта',
  retention_hold: 'Действует запрет удаления',
  call_in_progress: 'Звонок ещё идёт',
  precondition_failed: 'Настройки успели поменять: обновите экран и повторите',
  not_found: 'Не найдено',
}

function словами(status: number, code: string, detail?: string) {
  if (code === 'forbidden' && detail === 'role') return 'Нужна роль администратора компании: «Телефонию» настраивает только он'
  if (code === 'forbidden' && detail === 'company') return 'Узел обслуживает другую компанию пространства'
  if (status === 412) return ОШИБКИ.precondition_failed
  return ОШИБКИ[code] ?? detail ?? `Узел ответил ошибкой ${status}`
}

/** Узел не отвечает вовсе — это не «ошибка 500», а «узел недоступен». */
export function узелНедоступен(e: unknown) {
  return e instanceof TypeError || (e instanceof VoiceError && (e.status === 502 || e.status === 503 || e.status === 504))
}

// ——— Запрос ———

interface Опции {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  query?: Record<string, string | number | boolean | undefined | null>
  body?: unknown
  ifMatch?: string
}

export interface Ответ<T> { data: T; etag: string | null }

function адрес(path: string, query?: Опции['query']) {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
  }
  return url.toString()
}

async function запрос<T>(companyId: string, path: string, o: Опции = {}, повтор = true): Promise<Ответ<T>> {
  const { token } = await voiceToken(companyId)
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (o.body !== undefined) headers['Content-Type'] = 'application/json'
  if (o.ifMatch) headers['If-Match'] = o.ifMatch
  const res = await fetch(адрес(path, o.query), {
    method: o.method ?? 'GET', headers,
    body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
  })
  if (res.status === 401 && повтор) {
    // Токен мог истечь между выдачей и запросом (часы браузера, сон ноутбука): один
    // повтор с новым. Второй отказ — уже настоящая проблема входа, её показываем.
    забыть(companyId)
    return запрос<T>(companyId, path, o, false)
  }
  if (!res.ok) {
    let b: { error?: string; detail?: string; issues?: Issue[] } = {}
    try { b = await res.json() } catch { /* тело не JSON — хватит статуса */ }
    throw new VoiceError(res.status, b.error ?? String(res.status), словами(res.status, b.error ?? '', b.detail), b.issues)
  }
  const etag = res.headers.get('etag')
  if (res.status === 204) return { data: undefined as T, etag }
  return { data: await res.json() as T, etag }
}

async function дай<T>(companyId: string, path: string, query?: Опции['query']) {
  return (await запрос<T>(companyId, path, { query })).data
}

// ——— Общие типы ———

export interface Список<T> { items: T[]; next: string | null }

export interface OperatorRef {
  kind: 'staff' | 'cc'
  id: string
  name?: string | null
  connectionId?: string | null
}

export interface Actor { sub?: string; name?: string | null; kind?: 'user' | 'service' | 'node' | 'cc' }

export interface Issue { path: string; code: string; message?: string; level?: 'error' | 'warning' }

export type Outcome = 'connected' | 'abandoned' | 'fallback_message' | 'fallback_forward' | 'callback'
  | 'transferred' | 'interrupted' | 'callback_reached' | 'callback_not_reached' | 'callback_canceled'

export type ServedBy = 'cc' | 'local' | 'fallback' | 'none'

// ——— Кто я ———

export interface Me {
  sub: string
  name: string | null
  companyId: string
  role: 'admin'
  permissions: string[]
}

export const me = (cid: string) => дай<Me>(cid, '/me')

// ——— Сейчас ———

export type LiveState = 'ivr' | 'waiting' | 'offered' | 'dialing' | 'connected' | 'held' | 'parked'
  | 'consulting' | 'fallback' | 'wrapup'

export interface LiveContact {
  contactId: string
  lineId: string
  state: LiveState
  since: string
  waitSec: number | null
  priority: number
  flags: string[]
  number: string
  operator: OperatorRef | null
}

export interface LiveOperator {
  operator: OperatorRef
  presence: string
  busy: boolean
  contactId: string | null
}

export type AlertCode = 'trunk_down' | 'cc_offline' | 'sl_low' | 'disk_low' | 'delivery_stuck' | 'backup_stale'

export interface Alert {
  id: string
  code: AlertCode
  severity: 'critical' | 'warning'
  raisedAt: string
  detail: Record<string, unknown>
}

export interface Metrics {
  arrived?: number
  afterHours?: number
  offered?: number
  /** вошли в очередь линии переводом с другой линии: входят в offered, в arrived — нет */
  transferredIn?: number
  answered?: number
  answeredInSl?: number
  slPct?: number | null
  asaSec?: number | null
  waitP90Sec?: number | null
  waitMaxSec?: number | null
  abandoned?: number
  abandonedShort?: number
  abandonPct?: number | null
  fallback?: number
  fallbackPct?: number | null
  fallbackByReason?: Record<string, number>
  callbackOffered?: number
  callbackAccepted?: number
  callbackCreated?: number
  callbackExecuted?: number
  callbackReached?: number
  callbackOverdue?: number
  ahtSec?: number | null
  talkSec?: number | null
  holdSec?: number | null
  wrapSec?: number | null
  transferred?: number
  transferPct?: number | null
  repeatCallers?: number
  fcrPct?: number | null
  ccShare?: number | null
  noDisposition?: number
}

export interface NowSnapshot {
  at: string
  trunk: 'up' | 'down' | 'unknown'
  cc: { connectionId: string | null; online: boolean }
  today: Metrics
  contacts: LiveContact[]
  operators: LiveOperator[]
  callbacksDue: number
  alerts?: Alert[]
}

export const now = (cid: string) => дай<NowSnapshot>(cid, '/now')

/** Событие потока «Сейчас» — как его разложил `nowStream`. */
export type NowEvent =
  | { type: 'snapshot'; data: NowSnapshot }
  | { type: 'contact'; data: LiveContact | { contactId: string; state: 'ended' } }
  | { type: 'operator'; data: LiveOperator }
  | { type: 'trunk'; data: { trunk: NowSnapshot['trunk'] } }
  | { type: 'cc'; data: NowSnapshot['cc'] }
  | { type: 'stats'; data: { today: Metrics; callbacksDue: number } }
  | { type: 'alert'; data: (Alert & { state: 'raised' }) | { id: string; code: AlertCode; state: 'cleared' } }

/**
 * «Сейчас» потоком (SSE). `EventSource` не умеет заголовок Authorization, поэтому поток
 * читается `fetch`. Узел закрывает поток, когда истекает токен, — тогда переподключаемся
 * с новым; при обрыве — тоже, с паузой, растущей до 30 с. Возвращает функцию остановки.
 */
export function nowStream(cid: string, on: (e: NowEvent) => void, onState: (s: 'live' | 'reconnecting' | 'failed', e?: unknown) => void) {
  const ctl = new AbortController()
  let пауза = 1000

  async function раз() {
    const { token } = await voiceToken(cid)
    const res = await fetch(адрес('/now/stream'), {
      headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
      signal: ctl.signal,
    })
    if (res.status === 401) { забыть(cid); return }
    if (!res.ok || !res.body) {
      let b: { error?: string; detail?: string } = {}
      try { b = await res.json() } catch { /* без тела */ }
      throw new VoiceError(res.status, b.error ?? String(res.status), словами(res.status, b.error ?? '', b.detail))
    }
    onState('live')
    пауза = 1000
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
    let буфер = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) return
      буфер += value
      let i: number
      while ((i = буфер.indexOf('\n\n')) >= 0) {
        const кусок = буфер.slice(0, i)
        буфер = буфер.slice(i + 2)
        let type = 'message'
        const data: string[] = []
        for (const строка of кусок.split('\n')) {
          if (строка.startsWith('event:')) type = строка.slice(6).trim()
          else if (строка.startsWith('data:')) data.push(строка.slice(5).trimStart())
        }
        if (!data.length) continue // пинг — комментарий SSE
        try { on({ type, data: JSON.parse(data.join('\n')) } as NowEvent) } catch { /* битое событие пропускаем */ }
      }
    }
  }

  ;(async () => {
    while (!ctl.signal.aborted) {
      try {
        await раз()
      } catch (e) {
        if (ctl.signal.aborted) return
        // Отказ узла в правах не лечится переподключением — показываем и стоим.
        if (e instanceof VoiceError && (e.status === 403 || e.status === 429)) { onState('failed', e); return }
        onState('reconnecting', e)
        await new Promise(r => setTimeout(r, пауза))
        пауза = Math.min(пауза * 2, 30_000)
        continue
      }
      if (!ctl.signal.aborted) onState('reconnecting')
    }
  })()

  return () => ctl.abort()
}

// ——— Журнал звонков и карточка ———

export interface CallRow {
  contactId: string
  lineId: string
  direction?: 'inbound' | 'callback'
  number?: string
  numberPurged?: boolean
  identity?: string | null
  startedAt: string
  queuedAt?: string | null
  connectedAt?: string | null
  endedAt?: string | null
  waitSec?: number | null
  talkSec?: number | null
  holdSec?: number | null
  wrapSec?: number | null
  outcome?: Outcome | null
  servedBy?: ServedBy
  operator?: OperatorRef | null
  topic?: string | null
  flags?: string[]
  recorded?: boolean
  transcribed?: boolean
}

export interface Recording {
  id: string
  side: 'caller' | 'operator' | 'consult'
  leg?: number
  operator?: OperatorRef | null
  startedAt?: string
  durationSec?: number
  bytes?: number
  format?: 'wav' | 'ogg_opus'
  purged: boolean
  purgeAt?: string | null
}

export interface Callback {
  id: string
  originContactId?: string
  callContactId?: string | null
  state: 'scheduled' | 'dialing' | 'reached' | 'not_reached' | 'canceled'
  source: 'caller' | 'operator'
  number?: string
  dueAt?: string
  nextAt?: string | null
  attempts?: number
  maxAttempts?: number
  overdue?: boolean
  createdAt: string
  closedAt?: string | null
}

export interface CallCard extends CallRow {
  passportVersion?: number
  receptionVersion?: number | null
  hangupCause?: string | null
  stages?: { stage: string; at: string; detail?: Record<string, unknown> | null }[]
  disposition?: {
    code: string
    fields?: Record<string, unknown>
    createTicket?: boolean
    note?: string | null
    ticketRef?: string | null
    by?: OperatorRef
    at?: string
  } | null
  recordings?: Recording[]
  callbacks?: Callback[]
  delivered?: Record<string, string>
  retentionHold?: string | null
}

export interface CallsFilter {
  from?: string
  to?: string
  line?: string
  outcome?: Outcome | ''
  number?: string
  flags?: string
  cursor?: string
  limit?: number
}

export const calls = (cid: string, f: CallsFilter) => дай<Список<CallRow>>(cid, '/calls', { ...f })

export const call = (cid: string, contactId: string) =>
  дай<CallCard>(cid, `/calls/${encodeURIComponent(contactId)}`)

export async function callNumber(cid: string, contactId: string, reason: string) {
  return (await запрос<{ contactId: string; number: string }>(cid,
    `/calls/${encodeURIComponent(contactId)}/number`, { method: 'POST', body: { reason } })).data
}

export interface Segment { segmentId: string; side: 'caller' | 'operator'; startMs: number; endMs: number; text: string }

export const transcript = (cid: string, contactId: string, reason: string) =>
  дай<{ purgedAt?: string | null; segments: Segment[] }>(cid,
    `/calls/${encodeURIComponent(contactId)}/transcript`, { reason })

/** Разовая ссылка на звук: 60 с и одно открытие, `<audio>` не умеет заголовок Authorization. */
export async function recordingTicket(cid: string, contactId: string, recordingId: string, reason: string,
                                      purpose: 'play' | 'download' = 'play') {
  const t = (await запрос<{ url: string; expiresAt: string }>(cid,
    `/calls/${encodeURIComponent(contactId)}/recordings/${encodeURIComponent(recordingId)}/ticket`,
    { method: 'POST', body: { reason, purpose } })).data
  // Узел отдаёт путь, каким его видит браузер через кромку (`/voice/api/v1/media/…`);
  // на стенде API узла может жить на другом адресе — тогда путь ведём от него.
  return t.url.startsWith('http') ? t.url
    : import.meta.env.VITE_VOICE_API_URL ? адрес(t.url.replace(/^.*\/media\//, '/media/')) : new URL(t.url, CORE || window.location.origin).toString()
}

// ——— Журнал доступа ———

export interface AuditEntry {
  id: string
  at: string
  actor: Actor
  action: string
  object?: string | null
  reason?: string | null
  detail?: Record<string, unknown> | null
  ip?: string | null
}

export const audit = (cid: string, q: { contactId?: string; action?: string; actor?: string; from?: string; to?: string; cursor?: string; limit?: number }) =>
  дай<Список<AuditEntry>>(cid, '/audit', q)

// ——— Обратные звонки ———

export const callbacks = (cid: string, q: { state?: Callback['state'] | ''; overdue?: boolean; from?: string; to?: string; cursor?: string; limit?: number }) =>
  дай<Список<Callback>>(cid, '/callbacks', q)

export async function cancelCallback(cid: string, id: string, reason?: string) {
  return (await запрос<Callback>(cid, `/callbacks/${encodeURIComponent(id)}/cancel`,
    { method: 'POST', body: { reason } })).data
}

// ——— Статистика ———

export interface MetricDef { key: string; title: string; formula: string; unit?: string }

export interface StatsQuery { from: string; to: string; tz?: string; line?: string; servedBy?: ServedBy | '' }

export const statsDefinitions = (cid: string) => дай<MetricDef[]>(cid, '/stats/definitions')

export const statsSummary = (cid: string, q: StatsQuery) => дай<Metrics>(cid, '/stats/summary', { ...q })

export interface SeriesRow { start: string; group?: Record<string, string>; metrics: Metrics }

export const statsSeries = (cid: string, q: StatsQuery & { interval: '15m' | '1h' | '1d' | '1w' | '1mo'; groupBy?: string; metrics?: string }) =>
  дай<{ interval: string; tz?: string; rows: SeriesRow[] }>(cid, '/stats/series', { ...q })

export const statsOperators = (cid: string, q: { from: string; to: string; line?: string }) =>
  дай<{ operator: OperatorRef; metrics: Metrics }[]>(cid, '/stats/operators', q)

// ——— Настройки с версиями ———

export type ConfigKind = 'passport' | 'reception' | 'policy'
export type ConfigState = 'draft' | 'validated' | 'active' | 'retired'

export interface ConfigVersion<B = Record<string, unknown>> {
  kind: ConfigKind
  version: number
  state: ConfigState
  basedOn?: number | null
  body: B
  etag?: string
  comment?: string | null
  createdAt: string
  createdBy: Actor
  validatedAt?: string | null
  appliedAt?: string | null
  appliedBy?: Actor | null
}

export interface Validation { ok: boolean; hot?: boolean; breaking?: boolean; issues: Issue[] }

export interface ConfigDiff {
  kind: ConfigKind
  from: number
  to: number
  changes: { path: string; op: 'add' | 'remove' | 'replace'; from?: unknown; to?: unknown }[]
}

const к = (kind: ConfigKind) => `/config/${kind}`

export const configActive = (cid: string, kind: ConfigKind) => запрос<ConfigVersion>(cid, к(kind))

export const configVersions = (cid: string, kind: ConfigKind, q: { state?: ConfigState; cursor?: string; limit?: number } = {}) =>
  дай<Список<ConfigVersion>>(cid, `${к(kind)}/versions`, q)

export const configVersion = (cid: string, kind: ConfigKind, v: number) =>
  запрос<ConfigVersion>(cid, `${к(kind)}/versions/${v}`)

export async function configDraft(cid: string, kind: ConfigKind, b: { from?: number; body?: unknown; comment?: string } = {}) {
  return (await запрос<ConfigVersion>(cid, `${к(kind)}/versions`, { method: 'POST', body: b })).data
}

export const configSaveDraft = (cid: string, kind: ConfigKind, v: number, ifMatch: string, body: unknown, comment?: string) =>
  запрос<ConfigVersion>(cid, `${к(kind)}/versions/${v}`, { method: 'PUT', ifMatch, body: { body, comment } })

export async function configDeleteDraft(cid: string, kind: ConfigKind, v: number) {
  await запрос<void>(cid, `${к(kind)}/versions/${v}`, { method: 'DELETE' })
}

export async function configValidate(cid: string, kind: ConfigKind, v: number) {
  return (await запрос<Validation>(cid, `${к(kind)}/versions/${v}/validate`, { method: 'POST' })).data
}

/** Применить; `ifMatch` — ETag ДЕЙСТВУЮЩЕЙ версии. Прежняя версия здесь же — это откат. */
export const configApply = (cid: string, kind: ConfigKind, v: number, ifMatch: string, comment: string) =>
  запрос<ConfigVersion>(cid, `${к(kind)}/versions/${v}/apply`, { method: 'POST', ifMatch, body: { comment } })

export const configDiff = (cid: string, kind: ConfigKind, from: number, to?: number) =>
  дай<ConfigDiff>(cid, `${к(kind)}/diff`, { from, to })

export const configSchema = (cid: string, kind: ConfigKind) => дай<Record<string, unknown>>(cid, `${к(kind)}/schema`)

export const configChanges = (cid: string, q: { kind?: ConfigKind; from?: string; to?: string; cursor?: string; limit?: number } = {}) =>
  дай<Список<AuditEntry>>(cid, '/config/changes', q)

// ——— Сотрудники и переводы ———

export interface TransferTarget {
  code: string
  label: string
  kind: 'client_staff' | 'external'
  endpoint?: string | null
  places: { passport?: boolean; reception?: boolean; operatorControls?: boolean }
  issues: Issue[]
}

export interface TransferTargets {
  items: TransferTarget[]
  versions: { passport?: number; reception?: number }
  etag: string
  consistent: boolean
}

export const transferTargets = (cid: string) => дай<TransferTargets>(cid, '/config/transfer-targets')

export async function putTransferTargets(cid: string, ifMatch: string,
                                         items: { code: string; kind: TransferTarget['kind']; label: string; endpoint: string }[],
                                         comment?: string) {
  return (await запрос<TransferTargets>(cid, '/config/transfer-targets',
    { method: 'PUT', ifMatch, body: { items, comment } })).data
}

// ——— Контакт-центры ———

export interface CcConnection {
  id: string
  state: 'invited' | 'pending' | 'active' | 'suspended' | 'revoked'
  ccIssuer?: string | null
  fingerprint?: string | null
  kids?: string[]
  shellOrigin?: string | null
  online?: boolean
  lastEventSeq?: number
  ackedSeq?: number
  createdAt?: string
  activatedAt?: string | null
}

export interface CcOperator {
  operatorId: string
  role?: string
  state: 'invited' | 'admitted' | 'blocked'
  lines?: string[] | null
  presence?: string
  endpoint?: string | null
  updatedAt?: string
}

export const ccConnections = (cid: string) => дай<{ items: CcConnection[] }>(cid, '/cc/connections')

export async function ccInvite(cid: string) {
  return (await запрос<{ code: string; expiresAt: string; connectionId: string }>(cid, '/cc/invitations', { method: 'POST' })).data
}

export async function ccActivate(cid: string, id: string, fingerprint: string) {
  return (await запрос<CcConnection>(cid, `/cc/connections/${encodeURIComponent(id)}/activate`,
    { method: 'POST', body: { fingerprint } })).data
}

export async function ccState(cid: string, id: string, state: 'active' | 'suspended' | 'revoked', reason?: string) {
  return (await запрос<CcConnection>(cid, `/cc/connections/${encodeURIComponent(id)}/state`,
    { method: 'POST', body: { state, reason } })).data
}

export const ccOperators = (cid: string, id: string) =>
  дай<{ items: CcOperator[] }>(cid, `/cc/connections/${encodeURIComponent(id)}/operators`)

export async function ccOperator(cid: string, id: string, operatorId: string,
                                 b: { state: CcOperator['state']; role: 'operator' | 'supervisor'; lines?: string[] }) {
  return (await запрос<CcOperator>(cid,
    `/cc/connections/${encodeURIComponent(id)}/operators/${encodeURIComponent(operatorId)}`,
    { method: 'PUT', body: b })).data
}
