/**
 * NotificationCenter — колокольчик в Header с выпадающим списком уведомлений.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Check, CheckCheck, Trash2, X, Info, CircleCheck, AlertTriangle, OctagonX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  useNotifications,
  useUnreadCount,
  useMarkAsRead,
  useMarkAllAsRead,
  useDismissNotification,
  useClearNotifications,
} from '@/hooks/useNotifications'
import type { AppNotification, NotificationType } from '@/services/notificationService'
import { cn } from '@/lib/utils'

const typeIcon: Record<NotificationType, typeof Info> = {
  info: Info,
  success: CircleCheck,
  warning: AlertTriangle,
  error: OctagonX,
}

const typeColor: Record<NotificationType, string> = {
  info: 'text-blue-500',
  success: 'text-green-500',
  warning: 'text-yellow-500',
  error: 'text-red-500',
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'только что'
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} ч`
  const days = Math.floor(hours / 24)
  return `${days} д`
}

function NotificationItem({
  notification,
  onRead,
  onDismiss,
  onNavigate,
}: {
  notification: AppNotification
  onRead: () => void
  onDismiss: () => void
  onNavigate: (link: string) => void
}) {
  const Icon = typeIcon[notification.type]

  return (
    <div
      className={cn(
        'group relative flex gap-3 p-3 rounded-lg transition-colors cursor-default',
        !notification.read && 'bg-muted/50',
        notification.link && 'cursor-pointer hover:bg-muted/80',
      )}
      onClick={() => {
        if (!notification.read) onRead()
        if (notification.link) onNavigate(notification.link)
      }}
    >
      <div className={cn('mt-0.5 shrink-0', typeColor[notification.type])}>
        <Icon className="size-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className={cn('text-sm font-medium leading-tight', notification.read && 'text-muted-foreground')}>
            {notification.title}
          </p>
          <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
            {!notification.read && (
              <button
                className="p-0.5 rounded hover:bg-background"
                title="Прочитано"
                onClick={(e) => { e.stopPropagation(); onRead() }}
              >
                <Check className="size-3.5 text-muted-foreground" />
              </button>
            )}
            <button
              className="p-0.5 rounded hover:bg-background"
              title="Удалить"
              onClick={(e) => { e.stopPropagation(); onDismiss() }}
            >
              <X className="size-3.5 text-muted-foreground" />
            </button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{notification.message}</p>
        <p className="text-[10px] text-muted-foreground/60 mt-1">{formatRelativeTime(notification.createdAt)}</p>
      </div>
      {/* Unread dot */}
      {!notification.read && (
        <div className="absolute right-2 top-3 size-2 rounded-full bg-primary" />
      )}
    </div>
  )
}

export function NotificationCenter() {
  const navigate = useNavigate()
  const { data: notifications = [] } = useNotifications()
  const { data: unreadCount = 0 } = useUnreadCount()
  const markRead = useMarkAsRead()
  const markAllRead = useMarkAllAsRead()
  const dismiss = useDismissNotification()
  const clearAll = useClearNotifications()
  const [open, setOpen] = useState(false)

  const handleNavigate = (link: string) => {
    setOpen(false)
    navigate(link)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative h-9 w-9 rounded-lg shrink-0"
          aria-label="Уведомления"
        >
          <Bell className="h-4 w-4" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 inline-flex items-center justify-center rounded-full bg-primary text-primary-foreground text-[10px] font-bold min-w-[18px] h-[18px] px-1 leading-none">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="font-semibold text-sm">Уведомления</h3>
          <div className="flex items-center gap-1">
            {unreadCount > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={() => markAllRead.mutate()}
              >
                <CheckCheck className="size-3.5" />
                Все прочитаны
              </Button>
            )}
            {notifications.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs gap-1 text-muted-foreground"
                onClick={() => clearAll.mutate()}
              >
                <Trash2 className="size-3.5" />
              </Button>
            )}
          </div>
        </div>

        {/* List */}
        {notifications.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            Нет уведомлений
          </div>
        ) : (
          <ScrollArea className="max-h-[400px]">
            <div className="p-2 space-y-0.5">
              {notifications.map((n) => (
                <NotificationItem
                  key={n.id}
                  notification={n}
                  onRead={() => markRead.mutate(n.id)}
                  onDismiss={() => dismiss.mutate(n.id)}
                  onNavigate={handleNavigate}
                />
              ))}
            </div>
          </ScrollArea>
        )}
      </PopoverContent>
    </Popover>
  )
}
