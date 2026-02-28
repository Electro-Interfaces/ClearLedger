/**
 * React Query хуки для in-app уведомлений.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as svc from '@/services/notificationService'

const keys = {
  all: ['notifications'] as const,
  unread: ['notifications', 'unread'] as const,
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: keys.all })
  qc.invalidateQueries({ queryKey: keys.unread })
}

export function useNotifications() {
  return useQuery({
    queryKey: keys.all,
    queryFn: svc.getNotifications,
    refetchInterval: 30_000, // обновляем каждые 30 сек
  })
}

export function useUnreadCount() {
  return useQuery({
    queryKey: keys.unread,
    queryFn: svc.getUnreadCount,
    refetchInterval: 15_000,
  })
}

export function useMarkAsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: svc.markAsRead,
    onSuccess: () => invalidateAll(qc),
  })
}

export function useMarkAllAsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: svc.markAllAsRead,
    onSuccess: () => invalidateAll(qc),
  })
}

export function useDismissNotification() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: svc.dismissNotification,
    onSuccess: () => invalidateAll(qc),
  })
}

export function useClearNotifications() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: svc.clearAll,
    onSuccess: () => invalidateAll(qc),
  })
}
