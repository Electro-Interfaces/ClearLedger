/**
 * Аудит-сервис: запись и чтение событий (кто, когда, что сделал).
 * Dual-mode: localStorage (demo) / API.
 */

import type { AuditAction, AuditEvent } from '@/types'
import { isApiEnabled, get, post } from './apiClient'
import { getItem, setItem } from './storage'
import { nanoid } from 'nanoid'

const MAX_EVENTS = 5000

function auditKey(companyId: string): string {
  return `clearledger-audit-${companyId}`
}

function loadEvents(companyId: string): AuditEvent[] {
  return getItem<AuditEvent[]>(auditKey(companyId), [])
}

function saveEvents(companyId: string, events: AuditEvent[]): void {
  // Trim to MAX_EVENTS (keep newest)
  const trimmed = events.length > MAX_EVENTS ? events.slice(-MAX_EVENTS) : events
  setItem(auditKey(companyId), trimmed)
}

// ---- Public API ----

export interface LogEventParams {
  companyId: string
  entryId?: string
  action: AuditAction
  details?: string
  userId?: string
  userName?: string
}

/** Записать событие (fire-and-forget) */
export function logEvent(params: LogEventParams): void {
  const event: AuditEvent = {
    id: nanoid(),
    entryId: params.entryId,
    companyId: params.companyId,
    userId: params.userId ?? 'demo',
    userName: params.userName ?? 'Демо',
    action: params.action,
    details: params.details,
    timestamp: new Date().toISOString(),
  }

  if (isApiEnabled()) {
    post('/api/audit', event).catch(() => { /* best effort */ })
    return
  }

  const events = loadEvents(params.companyId)
  events.push(event)
  saveEvents(params.companyId, events)
}

export interface AuditFilters {
  action?: AuditAction
  entryId?: string
  dateFrom?: string
  dateTo?: string
}

/** Все события компании с фильтрацией */
export async function getEvents(companyId: string, filters?: AuditFilters): Promise<AuditEvent[]> {
  if (isApiEnabled()) {
    const params: Record<string, string> = { company_id: companyId }
    if (filters?.action) params.action = filters.action
    if (filters?.entryId) params.entry_id = filters.entryId
    if (filters?.dateFrom) params.date_from = filters.dateFrom
    if (filters?.dateTo) params.date_to = filters.dateTo
    return get<AuditEvent[]>('/api/audit', params)
  }

  let events = loadEvents(companyId)
  if (filters) {
    if (filters.action) events = events.filter((e) => e.action === filters.action)
    if (filters.entryId) events = events.filter((e) => e.entryId === filters.entryId)
    if (filters.dateFrom) events = events.filter((e) => e.timestamp >= filters.dateFrom!)
    if (filters.dateTo) events = events.filter((e) => e.timestamp <= filters.dateTo!)
  }
  return events
}

/** События конкретной записи */
export async function getEventsForEntry(companyId: string, entryId: string): Promise<AuditEvent[]> {
  return getEvents(companyId, { entryId })
}
