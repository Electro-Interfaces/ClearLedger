/**
 * Приглашения сотрудников по email. Управление — только в API-режиме.
 * Принятие приглашения (accept) — публичные эндпоинты.
 */
import { get, post, del } from './apiClient'
import type { TokenResponse } from './authService'

export interface Invitation {
  id: string
  email: string
  role: 'user' | 'admin'
  position?: string | null
  status: string
  created_at: string
  expires_at: string
  /** Готовая ссылка регистрации. Приходит ТОЛЬКО в ответ на создание и
   *  перевыпуск — в базе лежит хеш токена, позже ссылку не восстановить. */
  invite_url?: string | null
  /** Ушло ли письмо на самом деле (false — SMTP не настроен или сбой). */
  email_sent?: boolean | null
}

export interface AcceptPreview {
  email: string
  company_name: string
  role: 'user' | 'admin'
  user_exists: boolean
}

export async function listInvitations(companyId: string): Promise<Invitation[]> {
  return get<Invitation[]>('/api/invitations', { company_id: companyId })
}

export async function createInvitation(
  companyId: string, email: string, role: 'user' | 'admin', position?: string,
): Promise<Invitation> {
  return post<Invitation>('/api/invitations', {
    company_id: companyId, email, role, position: position || undefined,
  })
}

export async function revokeInvitation(id: string): Promise<void> {
  await del(`/api/invitations/${id}`)
}

export async function resendInvitation(id: string): Promise<Invitation> {
  return post<Invitation>(`/api/invitations/${id}/resend`)
}

// ─── Принятие (публичное) ───────────────────────────────────────────────────
export async function getAcceptPreview(token: string): Promise<AcceptPreview> {
  return get<AcceptPreview>(`/api/invitations/accept/${encodeURIComponent(token)}`)
}

/** Принять приглашение. Новый пользователь (name+password) → TokenResponse
 *  (автологин); существующий → {joined:true}. */
export async function acceptInvitation(
  token: string, data: { name?: string; password?: string },
): Promise<TokenResponse | { joined: true; user_exists: true }> {
  return post(`/api/invitations/accept/${encodeURIComponent(token)}`, data)
}
