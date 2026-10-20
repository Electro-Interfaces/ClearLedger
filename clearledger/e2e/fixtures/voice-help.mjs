/** Только вымышленные DTO для съёмки настоящих экранов. Рабочих URL и секретов нет. */
import { readFileSync } from 'node:fs'

export const companyId = 'help-meridian'
export const at = '2026-10-20T09:00:00.000Z'
const time = minutes => new Date(Date.parse(at) - minutes * 60_000).toISOString()
const configs = JSON.parse(readFileSync(new URL('./voice-help-config.json', import.meta.url)))
const actor = { sub: 'anna-demo', name: 'Анна Ветрова', kind: 'user' }
const operator = { kind: 'cc', id: 'anna-demo', name: 'Анна Ветрова' }
const connection = { id: 'cc-demo', state: 'active', ccIssuer: 'https://cc.example.invalid',
  shellOrigin: 'https://cc.example.invalid', fingerprint: 'DEMO:учебный-отпечаток', online: true,
  lastEventSeq: 132, ackedSeq: 132, createdAt: time(2000), activatedAt: time(1900) }
export const metrics = { arrived: 4, afterHours: 1, offered: 3, answered: 2,
  answeredInSl: 2, slPct: 66.7, asaSec: 16, waitP90Sec: 20, waitMaxSec: 24,
  abandoned: 1, abandonedShort: 0, abandonPct: 33.3, fallback: 1, fallbackPct: 25,
  fallbackByReason: { after_hours: 1 }, callbackCreated: 3, callbackExecuted: 2,
  callbackReached: 1, callbackOverdue: 1, ahtSec: 140, talkSec: 240, holdSec: 0,
  wrapSec: 40, transferred: 0, transferPct: 0, repeatCallers: 1, fcrPct: 50,
  ccShare: 75, noDisposition: 0, missed: 2, missedPct: 50, forwardAnswered: 0 }
const calls = ['connected', 'abandoned', 'connected', 'fallback_message'].map((outcome, i) => ({
  contactId: `demo-call-${i + 1}`, lineId: 'L-demo', direction: 'inbound', number: `•••010${i + 1}`,
  startedAt: time(30 + i * 12), queuedAt: time(30 + i * 12), connectedAt: outcome === 'connected' ? time(29 + i * 12) : null,
  endedAt: time(27 + i * 12), waitSec: 12 + i * 4, talkSec: outcome === 'connected' ? 120 : 0,
  outcome, servedBy: outcome === 'connected' ? 'cc' : 'none', operator: outcome === 'connected' ? operator : null,
  topic: 'charging_failed', flags: i === 2 ? ['repeat'] : [], recorded: outcome === 'connected', transcribed: outcome === 'connected',
}))
const debts = [null, { kind: 'cc' }, { kind: 'staff', id: 'engineer-demo', name: 'Илья Соколов' }].map((assignee, i) => ({
  id: `demo-debt-${i + 1}`, originContactId: 'demo-call-2', lineId: 'L-demo', state: 'scheduled', source: i ? 'operator' : 'caller',
  number: `•••020${i + 1}`, dueAt: time(i === 0 ? 10 : -20), nextAt: time(-15), attempts: i, maxAttempts: 3,
  overdue: i === 0, createdAt: time(45), assignee, result: null, missedCalls: i === 0 ? 3 : 1,
  contacts: [{ contactId: 'demo-call-2', kind: 'origin', startedAt: time(45), outcome: 'abandoned' }],
}))
const audit = [{ id: 'audit-demo-1', at: time(5), actor, action: 'recording.open', object: 'demo-call-1', reason: 'Проверка качества консультации', detail: {} },
  { id: 'audit-demo-2', at: time(70), actor, action: 'config.apply', object: 'reception@3', reason: 'Изменены часы приёма учебной линии', detail: {} }]
const parts = Object.fromEntries(['trunk', 'ari', 'cc', 'db', 'asr', 'llm', 'disk', 'cert', 'backup'].map(name => [name, {
  state: name === 'llm' ? 'off' : 'up', ok: true, critical: ['trunk', 'ari', 'cc', 'db'].includes(name),
  since: time(120), checkedAt: at, detail: name === 'llm' ? 'Языковая модель выключена' : 'Учебная проверка выполнена',
  ...(name === 'disk' ? { value: 72, unit: '%', info: { freeBytes: 72000000000, totalBytes: 100000000000 } } : {}),
  ...(name === 'backup' ? { value: 6, unit: 'h', info: { lastOkAt: time(360), thresholdH: 26 } } : {}),
}]))
const health = { ok: true, status: 'ok', at, startedAt: time(120), parts }
const now = { at, trunk: 'up', cc: { connectionId: 'cc-demo', online: true }, today: metrics, callbacksDue: 1, alerts: [],
  contacts: [{ contactId: 'demo-live-1', lineId: 'L-demo', state: 'waiting', since: time(0.3), waitSec: 18, priority: 50, flags: [], number: '•••0301', operator: null },
    { contactId: 'demo-live-2', lineId: 'L-demo', state: 'connected', since: time(2), waitSec: 12, priority: 50, flags: [], number: '•••0302', operator }],
  operators: [{ operator, presence: 'ready', busy: true, contactId: 'demo-live-2' },
    { operator: { kind: 'cc', id: 'ilya-demo', name: 'Илья Соколов' }, presence: 'ready', busy: false, contactId: null }] }
const webhook = { id: 'support-demo', url: 'https://support.example.invalid/voice/events',
  types: ['call.completed', 'callback.opened', 'callback.merged', 'callback.closed'], createdAt: time(400), lastStatus: 200, lastDeliveredAt: time(2), pending: 0 }
const reconciliation = { id: 'reconcile-demo', format: 'megafon_csv', period: { from: time(1440), to: at },
  uploadedAt: time(20), uploadedBy: actor, carrierRows: 5, badRows: 1, matched: 3, onlyCarrier: 1, onlyNode: 1, durationMismatch: 1,
  items: [{ kind: 'only_carrier', at: time(45), number: '•••0401', contactId: null }] }
const version = (kind, v = 3, state = 'active') => ({ kind, version: v, state, basedOn: 2, body: configs[kind],
  createdAt: time(120), createdBy: actor, appliedAt: state === 'active' ? time(100) : null,
  comment: state === 'active' ? 'Учебная линия: часы и запасной сценарий' : 'Пример изменения часов' })
let draft = false
export const definition = [
  ['arrived', 'Поступило', 'Входящие звонки за период', 'шт.'], ['answered', 'Отвечено', 'Звонки с ответом человека', 'шт.'],
  ['missed', 'Пропущено', 'Завершённые без ответа человека', 'шт.'], ['slPct', 'SL', 'Ответы в целевое время / предложенные × 100', '%'],
  ['asaSec', 'ASA', 'Среднее ожидание отвеченных звонков', 'с'], ['fcrPct', 'FCR', 'Решённые с первого звонка в окне повторов', '%'],
].map(([key, title, formula, unit]) => ({ key, title, formula, unit }))

export function megafon(query) {
  return { provider: 'megafon', company_id: companyId, period: { from: query.get('from'), to: query.get('to') },
    connection: { configured: true, status: 'ok', last_sync_at: time(2), last_error: null, mode: 'history', poll_interval_seconds: 300 },
    line: { name: 'Учебная линия', public_number: '+70000000001', forwarding_number: '+70000000002', origin_verified_per_call: false },
    summary: { total: 4, inbound: 4, outbound: 0, answered: 2, missed: 2, avg_wait_sec: 16, avg_talk_sec: 120, recordings: 2, operator_count: 1 },
    operators: [{ key: 'anna-demo', name: 'Анна Ветрова', login: 'anna-demo', extension: '101', user_id: 'anna-demo', total: 2, inbound_answered: 2, outbound: 0, missed: 0, avg_talk_sec: 120, avg_wait_sec: 16 }],
    groups: [{ name: 'Поддержка учебной сети', total: 4, answered: 2, missed: 2 }],
    filters: { operators: [{ key: 'anna-demo', name: 'Анна Ветрова' }], groups: [{ key: 'demo', name: 'Поддержка учебной сети' }], lines: [{ key: '+70000000001', name: 'Учебная линия', number: '+70000000001' }] },
    calls: { items: calls.map((call, i) => ({ id: call.contactId, call_id: `demo-history-${i}`, direction: 'inbound', missed: !call.connectedAt,
      client_phone: `+7000000010${i + 1}`, operator_name: call.operator?.name ?? null, operator_login: 'anna-demo', operator_user_id: call.operator?.id ?? null,
      group_name: 'Поддержка учебной сети', line_number: '+70000000001', line_name: 'Учебная линия', started_at: call.startedAt, wait_sec: call.waitSec,
      duration_sec: call.talkSec, has_recording: call.recorded, source: 'megafon_history', thread_id: null })), total: 4, page: 1, page_size: 25 } }
}

export function nodeReply(path, query, method) {
  if (path === '/me') return { sub: actor.sub, name: actor.name, companyId, role: 'admin', permissions: ['*'] }
  if (path === '/now') return now
  if (path === '/now/stream') return { sse: `event: snapshot\ndata: ${JSON.stringify(now)}\n\n` }
  if (path === '/calls') return { items: calls, next: null }
  if (/^\/calls\/[^/]+$/.test(path)) return { ...calls[0], passportVersion: 3, receptionVersion: 3, hangupCause: 'normal',
    stages: [{ stage: 'waiting', at: time(30) }, { stage: 'connected', at: time(29) }, { stage: 'completed', at: time(27) }],
    disposition: { code: 'charging_failed', fields: { station: 'Учебная ЭЗС-01' }, note: 'Зарядка восстановлена после консультации', by: operator },
    recordings: [{ id: 'recording-demo', side: 'caller', durationSec: 120, bytes: 1920044, format: 'wav', purged: false }],
    callbacks: [], ticketRefs: {}, delivered: {}, legs: [{ kind: 'queue', who: null, startedAt: time(30), endedAt: time(29), durationSec: 12, result: 'answered', recordings: [] },
      { kind: 'talk', who: { kind: 'cc', id: operator.id, label: operator.name }, startedAt: time(29), endedAt: time(27), durationSec: 120, result: 'completed', recordings: [{ recordingId: 'recording-demo', side: 'caller', offsetSec: 0, durationSec: 120 }] }] }
  if (path === '/callbacks') return { items: debts.filter(d => !query.get('overdue') || d.overdue), next: null }
  if (path.startsWith('/callbacks/')) return debts.find(d => d.id === path.split('/')[2])
  if (path === '/stats/definitions') return definition
  if (path === '/stats/summary') return metrics
  if (path === '/stats/series') return { rows: [{ start: time(60), group: { servedBy: 'cc', topic: 'charging_failed', cc: 'Учебный КЦ' }, metrics }] }
  if (path === '/stats/operators') return [{ operator, metrics }]
  if (path === '/stats/monthly') return { items: [], current: '2026-10', first: '2026-09', lines: [{ lineId: 'L-demo', name: 'Учебная линия' }] }
  if (path.startsWith('/stats/monthly/')) return { month: '2026-10', title: 'октябрь 2026', customer: 'Меридиан', lineId: 'L-demo', lineName: 'Учебная линия', tz: 'Europe/Moscow',
    period: { from: '2026-10-01T00:00:00Z', to: '2026-11-01T00:00:00Z' }, builtAt: at, status: 'current', version: null,
    params: { slaTargetSec: 20, fcrWindowMin: 30, shortAbandonSec: 5, callbackDueSec: 900, alertSlPct: 80 },
    kpis: definition.map(d => ({ ...d, value: metrics[d.key], previous: null })), metrics, previous: null,
    outcomes: [{ key: 'answered_cc', title: 'Ответил КЦ', count: 2, pct: 50 },
      { key: 'abandoned', title: 'Брошен в очереди', count: 1, pct: 25 },
      { key: 'fallback_message', title: 'Сообщение запасного сценария', count: 1, pct: 25 }], answeredWithin: [{ sec: 60, answered: 2, pct: 100 }],
    days: [{ date: '2026-10-20', metrics }], hours: [{ hour: 12, metrics }], topics: [{ topic: 'charging_failed', metrics }],
    reconciliations: [reconciliation], availability: { restarts: 0, downMin: {}, downs: {} } }
  if (path === '/stats/reconciliations') return { items: [reconciliation] }
  if (path.startsWith('/stats/reconciliations/')) return reconciliation
  if (path === '/config/transfer-targets') return { items: [{ code: 'duty_engineer', label: 'Дежурный инженер сети', kind: 'client_staff', endpoint: 'PJSIP/demo-engineer', places: { passport: true, reception: true, operatorControls: true }, issues: [] }], versions: { passport: 3, reception: 3 }, etag: '"help-3"', consistent: true }
  if (/^\/config\/(passport|reception|policy)\/diff$/.test(path)) return { kind: path.split('/')[2], from: Number(query.get('from')), to: Number(query.get('to')), changes: [] }
  const config = /^\/config\/(passport|reception|policy)(?:\/versions(?:\/(\d+)(?:\/(validate|simulate))?)?)?$/.exec(path)
  if (config) {
    const kind = config[1]
    if (config[3] === 'validate') return { ok: true, hot: true, issues: [] }
    if (method === 'POST' && path.endsWith('/versions')) { draft = true; return version(kind, 4, 'draft') }
    if (config[2]) return version(kind, Number(config[2]), Number(config[2]) === 4 ? 'draft' : 'active')
    if (path.endsWith('/versions')) return { items: query.get('state') === 'draft' ? (draft ? [version(kind, 4, 'draft')] : [])
      : query.get('state') === 'validated' ? [] : [version(kind), version(kind, 2, 'retired')], next: null }
    return version(kind)
  }
  if (path === '/cc/connections') return { items: [connection] }
  if (path.endsWith('/operators')) return { items: [{ operatorId: 'anna-demo', role: 'operator', state: 'admitted', presence: 'ready', lines: ['L-demo'], updatedAt: time(60) }] }
  if (path === '/health') return health
  if (path === '/health/history') return { items: [{ id: 'health-demo', part: query.get('part') || 'node', state: query.get('part') ? 'up' : 'started', at: time(120), code: 'demo', detail: 'Учебный запуск' }], next: null }
  if (path === '/node') return { customer: 'Меридиан', nodeVersion: '0.1.0', build: 'учебный пример', asterisk: '22', protocol: '0.10', startedAt: time(120), tz: 'Europe/Moscow',
    lines: [{ lineId: 'L-demo', name: 'Учебная линия', slaTargetSec: 20, hours: configs.reception.hours, inHours: true }], active: { passport: 3, reception: 3, policy: 3 },
    features: { operatorChannel: true, asr: true, llm: false, sounds: true, webhooks: true, trunkState: true, backupMark: true } }
  if (path === '/sounds') return { items: [{ name: 'demo-welcome', ref: 'sound:custom/demo-welcome', title: 'Приветствие учебной сети', durationSec: 8, bytes: 128044, sourceFormat: 'wav', usedBy: ['reception@3'], uploadedAt: time(180), uploadedBy: actor }] }
  if (path === '/sounds/places') return { items: [{ place: 'greeting', title: 'Приветствие', sounds: ['sound:custom/demo-welcome'] }, { place: 'callback_offer', title: 'Предложение перезвонить', sounds: ['sound:custom/demo-callback'] }], draft: null }
  if (path === '/webhooks') return { items: [webhook] }
  if (path.endsWith('/deliveries')) return { items: [{ eventId: 'event-demo', type: 'call.completed', at: time(2), state: 'delivered', status: 200, attempts: 1, deliveredAt: time(2) }] }
  if (path === '/audit') return { items: audit.filter(a => !query.get('action') || a.action === query.get('action')), next: null }
  if (path === '/connections') return { readonly: true, node: { url: 'https://node.example.invalid' }, core: { url: 'https://space.example.invalid', keyConfigured: true },
    space: { jwksUrl: 'https://space.example.invalid/api/sso/jwks', issuer: 'https://space.example.invalid', mtls: true, companyIds: [companyId] },
    asr: { configured: true, ready: true }, llm: { configured: false, ready: false }, trunkConfigured: true }
  return undefined
}

export function coreReply(path, query) {
  if (path === '/api/sso/token') return { token: 'help-fixture-only', expires_in: 300 }
  if (path === '/api/voice/megafon') return megafon(query)
  if (path === '/api/voice/connections') return { company_id: companyId, connections: ['megafon', 'asterisk'].map(provider => ({
    id: `demo-${provider}`, provider, enabled: true, status: 'ok', configured: true, endpoint: `https://${provider}.example.invalid`,
    sources: { endpoint: 'connector', api_key: 'connector', crm_token: 'connector', webhook_secret: 'connector' },
    readiness: { history: { configured: true, enabled: true }, events: { configured: true, enabled: true } }, webhook_path: '/demo/events', last_sync_at: time(2), last_error: null })) }
  if (path === '/api/voice/keys') return { keys: [] }
  if (path === '/api/tasks/people') return { people: [{ id: 'engineer-demo', name: 'Илья Соколов', partyType: 'internal' }] }
  return undefined
}
