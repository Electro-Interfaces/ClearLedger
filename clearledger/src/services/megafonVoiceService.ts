/** История МегаФон ВАТС в Ядре. Компания передаётся штатным apiClient в X-Company-Id. */
import * as api from '@/services/apiClient'

export type MegafonPeriod = 'today' | '7d' | '30d'
export interface MegafonParams {
  from: string
  to: string
  operator?: string
  group?: string
  line?: string
  missed?: 'true' | 'false'
  direction?: 'inbound' | 'outbound'
  search?: string
  page: number
  page_size: number
}

export interface MegafonCall {
  id: string
  call_id: string | null
  direction: 'inbound' | 'outbound' | null
  missed: boolean
  client_phone: string | null
  operator_name: string | null
  operator_login: string | null
  operator_user_id: string | null
  group_name: string | null
  line_number: string | null
  line_name: string | null
  started_at: string | null
  wait_sec: number | null
  duration_sec: number | null
  has_recording: boolean
  source: string | null
  thread_id: string | null
}

export interface MegafonOperator {
  key: string
  name: string | null
  login: string | null
  extension: string | null
  user_id: string | null
  total: number
  inbound_answered: number
  outbound: number
  missed: number
  avg_talk_sec: number | null
  avg_wait_sec: number | null
}

export interface MegafonVoiceData {
  provider: 'megafon'
  company_id: string
  period: { from: string; to: string }
  connection: {
    configured: boolean
    status: string
    last_sync_at: string | null
    last_error: string | null
    mode: 'history'
    poll_interval_seconds: number
  }
  line: {
    name: string | null
    public_number: string | null
    forwarding_number: string | null
    origin_verified_per_call: false
  }
  summary: {
    total: number; inbound: number; outbound: number; answered: number; missed: number
    avg_wait_sec: number | null; avg_talk_sec: number | null; recordings: number; operator_count: number
  }
  operators: MegafonOperator[]
  groups: { name: string; total: number; answered: number; missed: number }[]
  filters: {
    operators: { key: string; name: string }[]
    groups: { key: string; name: string }[]
    lines: { key: string; name: string; number: string }[]
  }
  calls: { items: MegafonCall[]; total: number; page: number; page_size: number }
}

/** Календарные дни в часовом поясе браузера; верхняя граница исключающая. */
export function megafonPeriodBounds(period: MegafonPeriod, now = new Date()) {
  const from = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  from.setDate(from.getDate() - (period === '30d' ? 29 : period === '7d' ? 6 : 0))
  const to = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  return { from: from.toISOString(), to: to.toISOString() }
}

export function megafonParamsFromUrl(url: URLSearchParams, now = new Date()): MegafonParams {
  const period = url.get('period')
  const fallback = megafonPeriodBounds(period === '7d' || period === '30d' ? period : 'today', now)
  const from = url.get('from') ?? ''
  const to = url.get('to') ?? ''
  const valid = Number.isFinite(Date.parse(from)) && Number.isFinite(Date.parse(to)) && Date.parse(from) < Date.parse(to)
  const missed = url.get('missed')
  const direction = url.get('direction')
  const search = (url.get('search') ?? '').replace(/\D/g, '')
  const page = Number(url.get('page') ?? '1')
  return {
    ...(valid ? { from: new Date(from).toISOString(), to: new Date(to).toISOString() } : fallback),
    operator: url.has('operator') ? url.get('operator')! : undefined,
    group: url.has('group') ? url.get('group')! : undefined,
    line: url.get('line') || undefined,
    missed: missed === 'true' || missed === 'false' ? missed : undefined,
    direction: direction === 'inbound' || direction === 'outbound' ? direction : undefined,
    search: search.length >= 4 ? search : undefined,
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    page_size: 25,
  }
}

function owned<T extends { company_id: string }>(data: T, companyId: string): T {
  if (!companyId || data.company_id !== companyId) throw new Error('Ответ относится к другой компании. Обновите страницу.')
  return data
}

export async function getMegafonVoice(companyId: string, params: MegafonParams): Promise<MegafonVoiceData> {
  if (!companyId) throw new Error('Выберите компанию')
  return owned(await api.get<MegafonVoiceData>('/api/voice/megafon', { ...params }), companyId)
}

export async function getMegafonCall(companyId: string, id: string): Promise<{ call: MegafonCall; provider: 'megafon'; company_id: string }> {
  if (!companyId) throw new Error('Выберите компанию')
  return owned(await api.get<{ call: MegafonCall; provider: 'megafon'; company_id: string }>(`/api/voice/megafon/calls/${encodeURIComponent(id)}`), companyId)
}
