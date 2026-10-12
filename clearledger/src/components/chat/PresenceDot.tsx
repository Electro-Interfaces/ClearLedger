/**
 * Точка присутствия собеседника: в сети · отошёл · не в сети.
 *
 * Источник — отметка Ядра (`online`): она есть у каждого, кто работает в системе.
 */
import { cn } from '@/lib/utils'

export type PresenceState = 'online' | 'away' | 'offline'

const TONE: Record<PresenceState, string> = {
  online: 'bg-emerald-500',
  away: 'bg-amber-500',
  offline: 'bg-muted-foreground/30',
}

const LABEL: Record<PresenceState, string> = {
  online: 'В сети',
  away: 'Отошёл',
  offline: 'Не в сети',
}

export function PresenceDot({ state, lastSeenAt, className, ring = false }: {
  state: PresenceState
  lastSeenAt?: string | null
  className?: string
  ring?: boolean
}) {
  const title = state === 'offline' && lastSeenAt
    ? `Был ${new Date(lastSeenAt).toLocaleString('ru-RU')}`
    : LABEL[state]
  return (
    <span
      className={cn('inline-block shrink-0 rounded-full', TONE[state], ring && 'ring-2 ring-card', className)}
      title={title}
    />
  )
}
