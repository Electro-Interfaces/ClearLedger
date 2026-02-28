/**
 * NotificationService — in-app уведомления.
 *
 * Dual-mode: localStorage (v0.2) / API (production).
 */

import { isApiEnabled, get, post, del } from './apiClient'
import { getItem, setItem } from './storage'
import { nanoid } from 'nanoid'

// ---- Types ----

export type NotificationType = 'info' | 'success' | 'warning' | 'error'

export interface AppNotification {
  id: string
  type: NotificationType
  title: string
  message: string
  /** Ссылка для перехода при клике */
  link?: string
  read: boolean
  createdAt: string
}

// ---- Storage key ----

const NOTIFICATIONS_KEY = 'clearledger-notifications'
const MAX_NOTIFICATIONS = 50

function loadAll(): AppNotification[] {
  return getItem<AppNotification[]>(NOTIFICATIONS_KEY, [])
}

function saveAll(items: AppNotification[]): void {
  // Обрезаем до MAX_NOTIFICATIONS, чтобы не раздувать localStorage
  setItem(NOTIFICATIONS_KEY, items.slice(0, MAX_NOTIFICATIONS))
}

// ---- CRUD ----

export async function getNotifications(): Promise<AppNotification[]> {
  if (isApiEnabled()) {
    return get<AppNotification[]>('/api/notifications')
  }
  return loadAll()
}

export async function getUnreadCount(): Promise<number> {
  if (isApiEnabled()) {
    const res = await get<{ count: number }>('/api/notifications/unread-count')
    return res.count
  }
  return loadAll().filter((n) => !n.read).length
}

export async function addNotification(
  input: Pick<AppNotification, 'type' | 'title' | 'message' | 'link'>,
): Promise<AppNotification> {
  if (isApiEnabled()) {
    return post<AppNotification>('/api/notifications', input)
  }
  const notification: AppNotification = {
    id: nanoid(),
    type: input.type,
    title: input.title,
    message: input.message,
    link: input.link,
    read: false,
    createdAt: new Date().toISOString(),
  }
  const all = loadAll()
  all.unshift(notification)
  saveAll(all)
  return notification
}

export async function markAsRead(id: string): Promise<void> {
  if (isApiEnabled()) {
    await post(`/api/notifications/${id}/read`)
    return
  }
  const all = loadAll()
  const item = all.find((n) => n.id === id)
  if (item) {
    item.read = true
    saveAll(all)
  }
}

export async function markAllAsRead(): Promise<void> {
  if (isApiEnabled()) {
    await post('/api/notifications/read-all')
    return
  }
  const all = loadAll()
  for (const n of all) n.read = true
  saveAll(all)
}

export async function dismissNotification(id: string): Promise<void> {
  if (isApiEnabled()) {
    await del(`/api/notifications/${id}`)
    return
  }
  const all = loadAll()
  saveAll(all.filter((n) => n.id !== id))
}

export async function clearAll(): Promise<void> {
  if (isApiEnabled()) {
    await del('/api/notifications')
    return
  }
  saveAll([])
}

// ---- Convenience: создание уведомлений по событиям ----

export function notifyIntakeComplete(count: number, errors: number): Promise<AppNotification> {
  const hasErrors = errors > 0
  return addNotification({
    type: hasErrors ? 'warning' : 'success',
    title: 'Приём завершён',
    message: hasErrors
      ? `Загружено ${count} документов, ${errors} с ошибками`
      : `Загружено ${count} ${count === 1 ? 'документ' : 'документов'}`,
    link: '/inbox',
  })
}

export function notifyVerification(entryTitle: string, approved: boolean): Promise<AppNotification> {
  return addNotification({
    type: approved ? 'success' : 'warning',
    title: approved ? 'Запись верифицирована' : 'Запись отклонена',
    message: entryTitle,
    link: '/inbox',
  })
}

export function notifyReconciliation(matched: number, unmatched: number): Promise<AppNotification> {
  return addNotification({
    type: unmatched > 0 ? 'warning' : 'success',
    title: 'Сверка завершена',
    message: `Сопоставлено: ${matched}, без пары: ${unmatched}`,
    link: '/reconciliation',
  })
}

export function notifyNewInboxItems(count: number): Promise<AppNotification> {
  return addNotification({
    type: 'info',
    title: 'Новые записи',
    message: `${count} ${count === 1 ? 'запись ожидает' : 'записей ожидают'} обработки`,
    link: '/inbox',
  })
}

export function notifyExportReady(format: string): Promise<AppNotification> {
  return addNotification({
    type: 'success',
    title: 'Экспорт готов',
    message: `Файл ${format.toUpperCase()} сформирован`,
    link: '/export',
  })
}
