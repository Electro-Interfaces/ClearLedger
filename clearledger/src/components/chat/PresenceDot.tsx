/**
 * Точка присутствия собеседника: в сети · отошёл · не в сети.
 *
 * Два источника, и это осознанно. Matrix знает точнее — клиент сам сообщает, жива ли
 * вкладка, а Synapse отличает «отошёл» (окно открыто, но человек не трогал его) от «не в
 * сети». Но знает он только про тех, кто открывал чат. Поэтому там, где Matrix молчит,
 * берётся отметка Ядра (`online`): она есть у каждого, кто вообще работает в системе.
 */
import { cn } from '@/lib/utils'
import type { PresenceState } from '@/services/matrix/matrixClient'

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

/** Свести два источника в одно состояние: Matrix точнее, отметка Ядра — запасная. */
export function resolvePresence(
  matrix: PresenceState | undefined, serverOnline: boolean | undefined,
): PresenceState {
  if (matrix) return matrix
  return serverOnline ? 'online' : 'offline'
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
