/**
 * Telegram-подобные утилиты чата: группировка сообщений, цветные имена,
 * разделители дат, скругление баблов. Порт из TSupport под camelCase-поля Ledger.
 */

// 8 цветов для имён (Telegram-стиль)
const NAME_COLORS = [
  'text-red-400', 'text-green-400', 'text-blue-400', 'text-yellow-500',
  'text-purple-400', 'text-pink-400', 'text-cyan-400', 'text-orange-400',
] as const

/** Детерминированный цвет для userId (hash → 1 из 8 цветов) */
export function getUserColor(userId: string): string {
  let hash = 0
  for (let i = 0; i < userId.length; i++) hash = ((hash << 5) - hash + userId.charCodeAt(i)) | 0
  return NAME_COLORS[Math.abs(hash) % NAME_COLORS.length]
}

/** Лейбл даты: «Сегодня», «Вчера», «15 февраля» */
export function getDateLabel(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = today.getTime() - msgDay.getTime()
  if (diff === 0) return 'Сегодня'
  if (diff === 86400000) return 'Вчера'
  return d.toLocaleDateString('ru', { day: 'numeric', month: 'long' })
}

/** Форматировать время HH:MM */
export function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })
}

export interface GroupingInfo {
  isFirstInGroup: boolean
  isLastInGroup: boolean
  showDate: boolean
}

/** Группировка: подряд от одного автора < 60 сек = группа. */
export function computeGrouping<T extends { userId?: string | null; createdAt: string }>(
  messages: T[],
): GroupingInfo[] {
  const result: GroupingInfo[] = []
  for (let i = 0; i < messages.length; i++) {
    const curr = messages[i]
    const prev = i > 0 ? messages[i - 1] : null
    const next = i < messages.length - 1 ? messages[i + 1] : null

    const currDay = new Date(curr.createdAt).toDateString()
    const prevDay = prev ? new Date(prev.createdAt).toDateString() : null
    const showDate = !prev || currDay !== prevDay

    const sameAsPrev = !!prev && prev.userId === curr.userId
      && Math.abs(new Date(curr.createdAt).getTime() - new Date(prev.createdAt).getTime()) < 60000
      && !showDate

    const sameAsNext = !!next && next.userId === curr.userId
      && Math.abs(new Date(next.createdAt).getTime() - new Date(curr.createdAt).getTime()) < 60000
      && new Date(curr.createdAt).toDateString() === new Date(next.createdAt).toDateString()

    result.push({ isFirstInGroup: !sameAsPrev, isLastInGroup: !sameAsNext, showDate })
  }
  return result
}

/** Класс скругления бабла по позиции в группе и стороне. */
export function bubbleRadius(isOwn: boolean, isFirst: boolean, isLast: boolean): string {
  if (isFirst && isLast) return isOwn ? 'rounded-2xl rounded-br-sm' : 'rounded-2xl rounded-bl-sm'
  if (isFirst) return 'rounded-2xl'
  if (isLast) return isOwn ? 'rounded-2xl rounded-br-sm' : 'rounded-2xl rounded-bl-sm'
  return 'rounded-2xl'
}
