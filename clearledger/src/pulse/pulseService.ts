/**
 * «Пульс» — рабочее место руководителя (ecosystem-deploy/docs/PULSE.md).
 * Модуль намеренно обособлен: экран и клиент живут в src/pulse/, наружу —
 * только маршрут в App.tsx и код продукта в реестре.
 */
import { del, get, patch, post, put } from '@/services/apiClient'

export interface PulseKpi {
  key: string
  title: string
  value: number | null
  unit: string | null
  delta_pct: number | null
  note: string | null
  /** null — норма; 'warn' — плитка просит внимания; 'stale' — данные устарели. */
  state: string | null
  /** Куда проваливаться с плитки: лестница погружения (PULSE.md §2). */
  link: string | null
  /** Рост — это хорошо? У потока заявок и молчащих станций — нет, у объёма — никак. */
  higher_is_better: boolean | null
  /** Ряд по неделям под цифрой — там, где важна не только дельта, но и форма. */
  spark?: (number | null)[]
}

export interface PulseCard {
  key: string
  title: string
  insight: string
  count: number | null
  level: 'warn' | 'alert'
  link: string | null
}

export interface PulseDay {
  /** Дата последней загруженной сессии — под ней живут все цифры сети. */
  as_of: string | null
  stale_days: number | null
  kpi: PulseKpi[]
  cards: PulseCard[]
  generated_at: string
}

// Путь передаётся ВМЕСТЕ с `/api`: BASE_URL в контейнере пуст (API на том же origin),
// и без префикса запрос уходит в SPA и возвращает index.html вместо JSON.
/**
 * `asRole` — посмотреть свой экран глазами роли (директор проверяет, что увидит
 * куратор). Права при этом не меняются: режим доступен только тому, кто и так
 * видит всё, и может лишь СУЗИТЬ картину.
 */
export const getPulseDay = (companyId: string, asRole?: string | null) =>
  get<PulseDay>('/api/pulse/day',
    asRole ? { company_id: companyId, as_role: asRole } : { company_id: companyId })

/**
 * Снять карточку: на сегодня («принято») или отложить на N дней.
 * Отложенная остаётся видимой в «Принятом» с датой возврата — это обязательство
 * руководителя, а не способ забыть.
 */
export const ackCard = (companyId: string, cardKey: string, snoozeDays?: number) =>
  post<{ ok: boolean; snooze_until: string | null }>('/api/pulse/ack',
    { company_id: companyId, card_key: cardKey, snooze_days: snoozeDays ?? null })

/* ── «Переписка»: живёт ли общение ───────────────────────────────────── */

export interface PulseComms {
  kpi: PulseKpi[]
  /** Кто из своих держит переписку (содержимое сообщений не передаётся). */
  authors: { name: string; messages: number; rooms: number; last: string | null }[]
  channels: { channel: string; threads: number; week: number; prev: number }[]
  rooms_total: number
  rooms_alive: number
  chat_last: string | null
  mail: { inbound: number; outbound: number; last: string | null }
}

export const getPulseComms = (companyId: string) =>
  get<PulseComms>('/api/pulse/comms', { company_id: companyId })

/* ── Доступ: то, что касается руководителя лично ─────────────────────── */

export interface PulseAccess {
  kpi: PulseKpi[]
  /** Кто не заходил дольше всех — с ролью, чтобы видеть спящие права. */
  dormant: { name: string; email: string; role: string; party: string | null
    last_seen: string | null }[]
  /** Изменения в составе и правах за месяц. */
  events: { at: string | null; action: string; who: string; details: string | null }[]
}

export const getPulseAccess = (companyId: string) =>
  get<PulseAccess>('/api/pulse/access', { company_id: companyId })

/* ── Источники: чему сегодня можно верить ────────────────────────────── */

export interface PulseSource {
  key: string
  label: string
  /** Какие разделы «Пульса» живут на этих данных. */
  feeds: string
  window: number
  count: number
  last_at: string | null
  days: number | null
  stale: boolean
}

export const getPulseSources = (companyId: string) =>
  get<{ items: PulseSource[]; stale: number
    channels: { name: string; status: string; docs: number; last_sync: string | null }[] }>(
    '/api/pulse/sources', { company_id: companyId })

/* ── Кто что видит: отбор картины для роли ───────────────────────────── */

export interface PulseVisibilityItem { key: string; label: string; section: string }

export interface PulseVisibilityRole {
  id: string
  name: string
  /** Роль с полным доступом — отбирать нечего. */
  full: boolean
  /** Ключ продукта целиком: видно всё, что есть в «Пульсе». */
  has_all: boolean
  items: string[]
  people: number
}

export const getPulseVisibility = (companyId: string) =>
  get<{ items: PulseVisibilityItem[]; roles: PulseVisibilityRole[] }>(
    '/api/pulse/visibility', { company_id: companyId })

export const savePulseVisibility = (companyId: string, roleId: string, items: string[]) =>
  put<{ ok: boolean; items: string[] }>('/api/pulse/visibility',
    { company_id: companyId, role_id: roleId, items })

/* ── Пороги эскалаций: норма компании, а не константа в коде ─────────── */

export interface PulseTarget {
  key: string
  value: number
  default: number
  /** true — значение изменено компанией, отличается от предложенного. */
  is_custom: boolean
  label: string
  hint: string
  unit: string
  section: string
}

export const getPulseTargets = (companyId: string) =>
  get<{ items: PulseTarget[] }>('/api/pulse/targets', { company_id: companyId })

/** null в значении — вернуть порог к предложенному по умолчанию. */
export const savePulseTargets = (companyId: string, values: Record<string, number | null>) =>
  put<{ ok: boolean; changed: string[] }>('/api/pulse/targets',
    { company_id: companyId, values })

/* ── «Бизнес»: картина для куратора ──────────────────────────────────── */

export interface PulseBusiness {
  as_of: string | null
  net: PulseKpi[]
  trend: { month: string; revenue: number; sessions: number }[]
  funnel: { stage: string; count: number }[]
  development: { commissioned_90d: number; commissioned_total: number; portfolio: number }
  events: { at: string | null; text: string }[]
}

export const getPulseBusiness = (companyId: string) =>
  get<PulseBusiness>('/api/pulse/business', { company_id: companyId })

/* ── «Где болит»: объект во всех контурах сразу ──────────────────────── */

export interface PulsePainPoint {
  id: string
  name: string
  code: string
  /** Сработавшие признаки: idle_cost · revenue_drop · docs_late · silent. */
  flags: string[]
  cost: number
  revenue: number
  revenue_prev: number
  late_docs: number
  last_session: string | null
  /** Цена вопроса: расходы точки плюс потерянная выручка. */
  at_risk: number
}

export interface PulseObjects {
  available: boolean
  kpi: PulseKpi[]
  pain: PulsePainPoint[]
  pain_count: number
  total: number
}

export const getPulseObjects = (companyId: string) =>
  get<PulseObjects>('/api/pulse/objects', { company_id: companyId })

/* ── «Эксплуатация»: хозяйство вокруг сети ───────────────────────────── */

export interface PulseOperations {
  available: boolean
  /** Текущий период — календарный месяц «YYYY-MM-01». */
  period: string
  kpi: PulseKpi[]
  /** Виды затрат: энергия, аренда и прочее — с суммой прошлого месяца. */
  items: { code: string; label: string; count: number; expected: number; previous: number }[]
  counterparties: { name: string; count: number; expected: number }[]
  /** Реестр месяцев: ждали ↔ чем подтверждено ↔ что просрочено. */
  periods: { period: string; charges: number; expected: number
    with_doc: number; overdue: number; status: string }[]
  open_periods: number
  docs_overdue_amount: number
  /** Основания расходов: договоры, у которых срок вышел или выйдет за 60 дней. */
  contracts: { number: string; counterparty: string; type: string
    valid_until: string; expired: boolean }[]
  contracts_expired: number
  contracts_ending: number
}

export const getPulseOperations = (companyId: string) =>
  get<PulseOperations>('/api/pulse/operations', { company_id: companyId })

/* ── «Проекты»: что компания строит ──────────────────────────────────── */

export interface PulseProjects {
  available: boolean
  kpi: PulseKpi[]
  /** Портфель по стадиям: сколько стоит и сколько из них застряло. */
  stages: { stage: string; label: string; count: number; avg_days: number | null; stuck: number }[]
  /** Долгожители поимённо: «46 застряло» задачей не становится, строка — да. */
  longest: { title: string; stage: string; days: number; region: string
    owner: string; next_action: string }[]
  /** Движение портфеля: переходы, гейты, документы. Правки полей — не движение. */
  moves: { at: string | null; kind: string; text: string }[]
  owners: { name: string; count: number }[]
}

export const getPulseProjects = (companyId: string) =>
  get<PulseProjects>('/api/pulse/projects', { company_id: companyId })

/* ── «Продажи»: деньги сети ──────────────────────────────────────────── */

export interface PulseSales {
  available: boolean
  /** Дата последней загруженной сессии: все окна считаются от неё, не от «сегодня». */
  as_of: string | null
  kpi: PulseKpi[]
  /** Станции, сильнее всего сдвинувшие недельную выручку — в обе стороны. */
  movers: { station: string; location_id: string; current: number; previous: number; delta: number }[]
  regions: { region: string; current: number; previous: number; stations: number }[]
  /** Работали неделю назад, молчат всю эту — поимённо. */
  out_stations: { station: string; location_id: string; lost: number; last_seen: string | null }[]
  stations_out: number
  stations_out_revenue: number
}

export const getPulseSales = (companyId: string) =>
  get<PulseSales>('/api/pulse/sales', { company_id: companyId })

/* ── «Обращения»: разговор с потребителем ────────────────────────────── */

export interface PulseContactCenter {
  /** false — телефонии в пространстве нет: экран говорит об этом прямо. */
  available: boolean
  as_of: string | null
  kpi: PulseKpi[]
  /** Профиль суток по московскому времени: где именно теряются звонки. */
  hours: { hour: number; calls: number; missed: number }[]
  operators: { name: string; calls: number; wait: number | null; talk: number | null }[]
  stuck?: number
  escalations?: number
  targets: Record<string, number>
}

export const getPulseContactCenter = (companyId: string) =>
  get<PulseContactCenter>('/api/pulse/contact-center', { company_id: companyId })

/* ── «Команда»: у кого затор ─────────────────────────────────────────── */

export interface PulsePerson {
  id: string
  name: string
  email: string
  department: string | null
  position: string | null
  is_head: boolean
  party: string | null
  last_seen: string | null
  /** Заявки: назначено на него, из них просрочено; сколько завёл и закрыл. */
  open: number
  breached: number
  authored: number
  closed_30d: number
  /** Проекты: сколько ведёт и сколько правок внёс за 30 дней. */
  projects_owned: number
  project_edits_30d: number
  /** Присутствие в общих контурах пространства. */
  chat_rooms: number
  actions_30d: number
}

/** Карточка человека: чем занят и что делал (разворот строки в «Команде»). */
export interface PulsePersonCard {
  found: boolean
  name: string
  email: string
  position: string | null
  department: string | null
  head: string | null
  party: string | null
  last_seen: string | null
  tickets: { number: string | null; title: string; status: string; breached: boolean
    object: string | null; created: string | null }[]
  projects: { title: string; stage: string }[]
  rooms: { name: string; kind: string | null; count: number }[]
  actions: { action: string; at: string | null; details: unknown }[]
  edits: { week: number; month: number; last: string | null }
}

export const getPulsePerson = (companyId: string, userId: string) =>
  get<PulsePersonCard>(`/api/pulse/team/${userId}`, { company_id: companyId })

export interface PulseTeam {
  people: PulsePerson[]
  departments: { name: string; head: string | null; people: number }[]
}

export const getPulseTeam = (companyId: string) =>
  get<PulseTeam>('/api/pulse/team', { company_id: companyId })

/* ── «Неделя»: дайджест ──────────────────────────────────────────────── */

export interface PulseWeek {
  as_of: string | null
  rows: {
    label: string; value: number; prev: number | null; unit: string | null
    /** Рост — это хорошо? У «Заявок поступило» — нет. */
    higher_is_better: boolean
  }[]
  highlights: { at: string | null; text: string }[]
}

export const getPulseWeek = (companyId: string) =>
  get<PulseWeek>('/api/pulse/week', { company_id: companyId })

/* ── «Принятое сегодня»: что уже сняли с экрана дня ──────────────────── */

export interface PulseAccepted {
  card_key: string
  title: string
  on: string
  at: string | null
  who: string | null
  note: string | null
  /** Дата возврата, если карточку отложили, а не просто приняли. */
  snooze_until: string | null
  today: boolean
}

export const getPulseAccepted = (companyId: string) =>
  get<{ items: PulseAccepted[] }>('/api/pulse/accepted', { company_id: companyId })

/* ── Витрины: «Пульс», повёрнутый наружу ─────────────────────────────── */

export interface PulseViewRow {
  id: string; name: string; audience: string; period: string
  owner: string | null; note: string; status: string
  updatedAt: string | null; blocks: number; people: number
}

export interface PulseViewCard {
  id: string; name: string; audience: string; period: string
  owner: string | null; note: string; status: string
  blocks: { key: string; title: string; originalTitle: string; hint: string | null }[]
  people: { id: string; name: string; email: string }[]
  /** Роли, которым показана витрина. */
  roles: { id: string; name: string }[]
  canEdit: boolean; asOf: string
}

export interface PulseViewData {
  id: string; name: string; audience: string; company: string | null
  owner: string | null; note: string; status: string; asOf: string
  period: string; periodLabel: string
  /** Можно ли писать с витрины: кнопка, которая ничего не делает, хуже её отсутствия. */
  canWrite: boolean
  blocks: {
    key: string; title: string; hint: string | null
    metrics: {
      label: string; value: string; tone?: string | null
      /** Сравнение с прошлым окном; null — базы сравнения нет, и врать нечем. */
      delta?: { text: string; tone: string | null } | null
    }[]
    items: { title: string; detail?: string; amount?: string; requestId?: string }[]
    note: string | null
    /** Куда идти, если нужно разобраться глубже: витрина не заменяет приложение. */
    link?: { title: string; href: string } | null
  }[]
}

export const getPulseViews = (companyId: string) =>
  get<{
    views: PulseViewRow[]
    catalog: { key: string; title: string; group: string }[]
    periods: { key: string; title: string }[]
  }>('/api/pulse/views', { company_id: companyId })

export const getPulseView = (companyId: string, id: string) =>
  get<PulseViewCard>(`/api/pulse/views/${id}`, { company_id: companyId })

export const getPulseViewData = (companyId: string, id: string) =>
  get<PulseViewData>(`/api/pulse/views/${id}/data`, { company_id: companyId })

export const getPulseMyViews = (companyId: string) =>
  get<{ views: { id: string; name: string; audience: string; owner: string | null }[] }>(
    '/api/pulse/my-views', { company_id: companyId })

export const createPulseView = (companyId: string, name: string) =>
  post<{ id: string; name: string; status: string }>(
    `/api/pulse/views?company_id=${companyId}&name=${encodeURIComponent(name)}`, {})

export const updatePulseView = (
  companyId: string, id: string,
  v: { name?: string; audience?: string; owner_name?: string; note?: string; status?: string },
) => patch<{ id: string; status: string }>(
  `/api/pulse/views/${id}?company_id=${companyId}`
  + Object.entries(v).filter(([, x]) => x !== undefined && x !== null)
      .map(([k, x]) => `&${k}=${encodeURIComponent(String(x))}`).join(''), {})

/** Состав приходит целиком: перетаскивание блоков — одно действие человека. */
export const setPulseViewBlocks = (
  companyId: string, id: string, blocks: { key: string; title?: string; hint?: string }[],
) => put<{ blocks: number; skipped: number }>(
  `/api/pulse/views/${id}/blocks?company_id=${companyId}`, { blocks })

export const setPulseViewGrants = (companyId: string, id: string, users: string[]) =>
  put<{ granted: number; skipped: number }>(
    `/api/pulse/views/${id}/grants?company_id=${companyId}`, { users })

/** Обращение с витрины: уходит задачей и/или сообщением в чат — своего ящика нет. */
export const sendPulseFeedback = (
  companyId: string, viewId: string, v: { text: string; blockTitle?: string },
) => post<{ sent: boolean; task: { id: string; number: number } | null
            chat: { roomId: string } | null }>(
  `/api/pulse/views/${viewId}/feedback?company_id=${companyId}`, v)

/** Ответ по строке «Чего ждём от вас» — идёт в само требование. */
export const replyPulseRequest = (
  companyId: string, viewId: string,
  v: { requestId: string; decision: 'sent' | 'will_send' | 'declined' | 'question'; note?: string },
) => post<{ ok: boolean; status: string; answer: string
            task: { id: string; number: number } | null }>(
  `/api/pulse/views/${viewId}/reply?company_id=${companyId}`, v)

/* ── Ссылки на витрину: показ тому, у кого нет учётки ─────────────────── */

export interface PulseViewLink {
  id: string; token: string; label: string
  expiresAt: string | null; revoked: boolean; expired: boolean
  opened: number; lastOpenedAt: string | null; url: string
}

export const getPulseViewLinks = (companyId: string, viewId: string) =>
  get<{ links: PulseViewLink[] }>(`/api/pulse/views/${viewId}/links`,
    { company_id: companyId })

export const createPulseViewLink = (
  companyId: string, viewId: string, v: { label: string; days: number },
) => post<{ id: string; token: string; url: string; expiresAt: string }>(
  `/api/pulse/views/${viewId}/links?company_id=${companyId}`
  + `&label=${encodeURIComponent(v.label)}&days=${v.days}`, {})

export const revokePulseViewLink = (companyId: string, viewId: string, id: string) =>
  del<{ revoked: boolean }>(`/api/pulse/views/${viewId}/links/${id}?company_id=${companyId}`)

/** Витрина по ссылке — без авторизации, только чтение. */
export const getShowcaseByToken = (token: string) =>
  get<PulseViewData>(`/api/showcase/${token}`)

/** Роли, которым показана витрина: «настроили для роли» вместо поимённой выдачи. */
export const setPulseViewRoles = (companyId: string, viewId: string, roles: string[]) =>
  put<{ roles: number; skipped: number }>(
    `/api/pulse/views/${viewId}/roles?company_id=${companyId}`, { roles })
