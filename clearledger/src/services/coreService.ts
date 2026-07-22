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
