/**
 * Словарь и форматы «Задач» — одни на все экраны продукта.
 *
 * Слова общие с «Заявками»: одна и та же срочность не должна называться
 * по-разному в двух продуктах одного пространства. Держим в отдельном файле,
 * потому что их читают и список, и карточка, и окно из шапки, и обзор — четыре
 * копии разъехались бы на первой же правке.
 */
export const PRIORITY_LABEL: Record<string, string> = {
  low: 'низкая', medium: 'обычная', high: 'срочная', critical: 'критичная',
}

export const PRIORITY_TONE: Record<string, string> = {
  critical: 'text-red-600 dark:text-red-400',
  high: 'text-amber-600 dark:text-amber-400',
}

export const STATUS_LABEL: Record<string, string> = {
  open: 'в работе', done: 'выполнена', cancelled: 'отменена',
}

/** Как связь называется со стороны открытой карточки. */
export const LINK_LABEL: Record<string, string> = {
  subtask: 'подзадача', parent: 'родительская',
  blocks: 'блокирует', blocked_by: 'заблокирована',
  relates: 'связана', duplicates: 'дублирует', duplicated_by: 'дублируется',
}

export const dt = (s: string | null) => (s ? new Date(s).toLocaleDateString('ru-RU') : '—')

export const dtT = (s: string | null) => (s
  ? new Date(s).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  : '—')

/** Человеческий размер файла: «1,2 МБ» вместо 1258291. */
export const fileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

/** Строка события ленты: что именно произошло. */
export function eventText(e: { kind: string; from: string | null; to: string | null }): string {
  switch (e.kind) {
    case 'created': return `поставил задачу · ${e.to ?? ''}`
    case 'stage': return `стадия: ${e.from ?? '—'} → ${e.to ?? '—'}`
    case 'assign': return e.to ? `исполнитель: ${e.from ?? '—'} → ${e.to}` : 'снял исполнителя'
    case 'status':
      return `статус: ${STATUS_LABEL[e.from ?? ''] ?? e.from} → ${STATUS_LABEL[e.to ?? ''] ?? e.to}`
    case 'field': return `${e.from ?? 'поле'} → ${e.to ?? '—'}`
    case 'delegate': return `поручил внешнему участнику: ${e.to ?? '—'}`
    case 'mail': return 'ответил письмом'
    case 'external_stage': return `этап внешней системы: ${e.to ?? '—'}`
    default: return 'написал'
  }
}

/** Где сейчас мяч — словами, одинаковыми с «Заявками». */
export const WAITING_LABEL: Record<string, string> = {
  external: 'ждём внешнюю сторону', us: 'мяч у нас',
}
