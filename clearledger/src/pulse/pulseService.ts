/**
 * «Пульс» — рабочее место руководителя (ecosystem-deploy/docs/PULSE.md).
 * Модуль намеренно обособлен: экран и клиент живут в src/pulse/, наружу —
 * только маршрут в App.tsx и код продукта в реестре.
 */
import { get, post } from '@/services/apiClient'

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
  /** Рост — это хорошо? У потока заявок и молчащих станций — нет. */
  higher_is_better: boolean
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
export const getPulseDay = (companyId: string) =>
  get<PulseDay>('/api/pulse/day', { company_id: companyId })

export const ackCard = (companyId: string, cardKey: string) =>
  post<{ ok: boolean }>('/api/pulse/ack', { company_id: companyId, card_key: cardKey })

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
  rooms: { name: string; kind: string | null }[]
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
  today: boolean
}

export const getPulseAccepted = (companyId: string) =>
  get<{ items: PulseAccepted[] }>('/api/pulse/accepted', { company_id: companyId })
