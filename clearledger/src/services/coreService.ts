/**
 * Клиент состояния Ядра экосистемы (Центр управления → Обзор).
 * Бэкенд: routers/core_router.py — GET /api/core/status (только суперадмин).
 */
import { get } from './apiClient'

export interface CoreServiceStatus {
  code: string
  name: string
  configured: boolean
  status: 'up' | 'down' | 'configured' | 'not_configured' | string
}

export interface CoreStatus {
  version: string
  env: string
  sso: { enabled: boolean; issuer: string; kid: string; jwksKeys: number; apps: number }
  registry: { apps: number; modules: number }
  counts: { companies: number; users: number }
  services: CoreServiceStatus[]
}

export async function getCoreStatus(): Promise<CoreStatus> {
  return get<CoreStatus>('/api/core/status')
}

export interface CoreAuditEvent {
  id: string
  companyId: string
  companySlug: string
  companyName: string
  userId: string
  userName: string
  action: string
  details?: string | null
  timestamp?: string | null
}

/** Аудит по всей экосистеме (суперадмин). */
export async function getCoreAudit(
  params?: { limit?: number; action?: string; company_id?: string },
): Promise<CoreAuditEvent[]> {
  return get<CoreAuditEvent[]>('/api/core/audit', params)
}
