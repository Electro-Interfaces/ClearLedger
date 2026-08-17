/**
 * Telegram-подобные утилиты чата: группировка сообщений, цветные имена,
 * разделители дат, скругление баблов. Порт из TSupport под camelCase-поля Ledger.
 */

// 8 цветов для имён (Telegram-стиль). Каждый — парой на обе темы: 400-е тона
// читаются на тёмном, но растворяются на светлом фоне (жёлтый — первым).
const NAME_COLORS = [
  'text-red-600 dark:text-red-400', 'text-green-700 dark:text-green-400',
  'text-blue-600 dark:text-blue-400', 'text-amber-600 dark:text-yellow-400',
  'text-purple-600 dark:text-purple-400', 'text-pink-600 dark:text-pink-400',
  'text-cyan-700 dark:text-cyan-400', 'text-orange-600 dark:text-orange-400',
] as const

/** Детерминированный цвет для userId (hash → 1 из 8 цветов) */
export function getUserColor(userId: string): string {
  let hash = 0
  for (let i = 0; i < userId.length; i++) hash = ((hash << 5) - hash + userId.charCodeAt(i)) | 0
  return NAME_COLORS[Math.abs(hash) % NAME_COLORS.length]
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
}

/** Лейбл даты: «Сегодня», «Вчера», «15 февраля», «15 февраля 2025 г.» */
export function getDateLabel(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  if (Number.isNaN(d.getTime())) return 'Дата неизвестна'
  if (isSameLocalDay(d, now)) return 'Сегодня'
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (isSameLocalDay(d, yesterday)) return 'Вчера'
  return d.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric',
  })
}

/** Форматировать время HH:MM */
export function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

/** Полная дата для подсказки и скринридера. */
export function formatFullDateTime(dateStr: string): string {
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return 'Дата и время неизвестны'
  return d.toLocaleString('ru-RU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
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
