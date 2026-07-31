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
  /** null — норма; 'warn' — жёлтая плитка; 'stale' — данные стухли (PULSE.md §6). */
  state: string | null
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
  name: string
  email: string
  department: string | null
  is_head: boolean
  party: string | null
  last_seen: string | null
  open: number
  breached: number
}

export interface PulseTeam {
  people: PulsePerson[]
  departments: { name: string; head: string | null; people: number }[]
}

export const getPulseTeam = (companyId: string) =>
  get<PulseTeam>('/api/pulse/team', { company_id: companyId })

/* ── «Неделя»: дайджест ──────────────────────────────────────────────── */

export interface PulseWeek {
  as_of: string | null
  rows: { label: string; value: number; prev: number | null; unit: string | null }[]
  highlights: { at: string | null; text: string }[]
}

export const getPulseWeek = (companyId: string) =>
  get<PulseWeek>('/api/pulse/week', { company_id: companyId })
