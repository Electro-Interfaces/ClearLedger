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

export const getPulseDay = (companyId: string) =>
  get<PulseDay>('/pulse/day', { company_id: companyId })

export const ackCard = (companyId: string, cardKey: string) =>
  post<{ ok: boolean }>('/pulse/ack', { company_id: companyId, card_key: cardKey })
