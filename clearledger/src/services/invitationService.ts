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
  /** Кем человек войдёт в пространство — задаётся при приглашении, не после входа. */
  party_type?: 'internal' | 'partner' | 'vendor'
  organization_id?: string | null
  organization_name?: string | null
  /** Куда позвали: в одну организацию или в пространство целиком. */
  scope?: InviteScope
}

/**
 * Пространство и организация — разные вещи. «Аудит» это ИМЯ ПРОСТРАНСТВА, внутри
 * которого живут своя практика и обслуживаемые организации; позвать можно и во всё
 * пространство (доступ ко всем организациям), и в одну — чаще нужно второе.
 */
export type InviteScope = 'company' | 'space'

export interface AcceptPreview {
  email: string
  company_name: string
  role: 'user' | 'admin'
  user_exists: boolean
  /** Должность из приглашения — предзаполняет форму, приглашённый может поправить. */
  position?: string | null
  /** До какого момента действует ссылка — страница показывает срок явно. */
  expires_at?: string | null
  scope?: InviteScope
  /** Имя пространства (бренд контейнера) — может не совпадать с именем организации. */
  space_name?: string | null
  /** Организации пространства при scope=space: куда именно откроется доступ. */
  space_companies?: string[]
}

export async function listInvitations(companyId: string): Promise<Invitation[]> {
  return get<Invitation[]>('/api/invitations', { company_id: companyId })
}

export async function createInvitation(
  companyId: string, email: string, role: 'user' | 'admin', position?: string,
  party?: {
    partyType?: 'internal' | 'partner' | 'vendor'
    organizationId?: string
    scope?: InviteScope
  },
): Promise<Invitation> {
  return post<Invitation>('/api/invitations', {
    company_id: companyId, email, role, position: position || undefined,
    party_type: party?.partyType,
    organization_id: party?.organizationId || undefined,
    scope: party?.scope ?? 'company',
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
 *  (автологин); существующий → {joined:true}. position — уточнённая должность. */
export async function acceptInvitation(
  token: string, data: { name?: string; password?: string; position?: string },
): Promise<TokenResponse | { joined: true; user_exists: true }> {
  return post(`/api/invitations/accept/${encodeURIComponent(token)}`, data)
}
