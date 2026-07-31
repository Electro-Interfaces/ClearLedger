/**
 * Приложение «Заявки» — трекер пространства (docs/TICKETS.md ecosystem-deploy).
 * Данные — витрина контура Поддержки через бэкенд Ядра; создание — эко-каналом.
 */
import { get, post } from './apiClient'

export interface SpaceTicket {
  id: string
  number: string | null
  title: string
  status: string
  stage: string | null
  stage_color: string | null
  priority: string
  type: string | null
  category: string | null
  /** «У кого мяч»: чья сторона держит заявку прямо сейчас. */
  responsibility: string | null
  assignee: string | null
  object: string | null
  /** Зеркало внешней системы (hubex и т.п.); null — своя заявка. */
  external_system: string | null
  sla_deadline: string | null
  sla_breached: boolean
  created_at: string | null
  updated_at: string | null
}

export interface TicketsSummary {
  open: number
  sla_breached: number
  created_7d: number
  closed_7d: number
  created_30d: number
  closed_30d: number
  by: Record<'responsibility' | 'status' | 'category' | 'assignee' | 'department',
    { key: string; count: number }[]>
}

export interface MaintenanceSchedule {
  id: string
  name: string
  description: string | null
  interval_days: number
  lead_days: number | null
  category: string | null
  priority: string | null
  next_due_date: string | null
  is_active: boolean
  object: string | null
}

export type TicketScope = 'open' | 'mine' | 'closed' | 'all'

export interface TicketDetails extends SpaceTicket {
  description: string | null
  author: string | null
  eco_object_id: string | null
  /** Обсуждение, из которого заявка родилась (кнопка «В заявку» в чате). */
  origin_room: { room_id: string; room_name: string } | null
  /** Точка эскалации по штатной структуре: руководитель подразделения исполнителя. */
  escalation: { department: string | null; to: string } | null
}

export async function listTickets(companyId: string, scope: TicketScope, objectId?: string) {
  return get<{ tickets: SpaceTicket[]; total: number }>(
    '/api/tickets', { company_id: companyId, scope, object_id: objectId || undefined })
}

export async function ticketDetails(id: string, companyId: string) {
  return get<TicketDetails>(`/api/tickets/${id}`, { company_id: companyId })
}

export async function ticketsSummary(companyId: string) {
  return get<TicketsSummary>('/api/tickets/summary', { company_id: companyId })
}

export async function listSchedules(companyId: string) {
  return get<{ schedules: MaintenanceSchedule[] }>(
    '/api/tickets/schedules', { company_id: companyId })
}

export async function createTicket(data: {
  companyId: string; objectId: string; description: string
  title?: string; priority?: string
}) {
  return post('/api/tickets', {
    company_id: data.companyId, object_id: data.objectId,
    description: data.description, title: data.title || undefined,
    priority: data.priority || 'medium',
  })
}
