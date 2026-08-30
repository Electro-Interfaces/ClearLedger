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

/** Приоритет, о котором стоит сказать вслух.
 *
 *  «Обычная» — значение по умолчанию: оно есть у большинства строк и потому не
 *  различает их, а место в мете занимает на каждой. Ровно та же причина, по
 *  которой из даты убран год. Говорим только про то, что выбивается: срочное,
 *  критичное и — в другую сторону — низкое.
 */
export const priorityWord = (p: string | null | undefined): string | null =>
  (!p || p === 'medium' ? null : PRIORITY_LABEL[p] ?? null)

export const PRIORITY_TONE: Record<string, string> = {
  critical: 'text-red-600 dark:text-red-400',
  high: 'text-amber-600 dark:text-amber-400',
}

export const STATUS_LABEL: Record<string, string> = {
  open: 'в работе', done: 'выполнена', cancelled: 'отменена',
}

/** Общая ось состояния работы (этап 13а): одни и те же колонки для
 *  документа и для поручения. Порядок = порядок движения работы и порядок
 *  колонок на доске. Список тот же, что на сервере (`work_state.COLUMNS`):
 *  сервер отдаёт его в `/api/tasks/types`, а здесь он живёт для тех экранов,
 *  которые рисуют колонки до первого ответа. */
export const WORK_COLUMNS: { code: string; name: string }[] = [
  { code: 'new', name: 'Заведено' },
  { code: 'in_work', name: 'В работе' },
  { code: 'approval', name: 'На согласовании' },
  { code: 'external', name: 'Ждём внешних' },
  { code: 'done', name: 'Готово' },
]

export const WORK_COLUMN_LABEL: Record<string, string> = Object.fromEntries(
  WORK_COLUMNS.map((c) => [c.code, c.name]))

/** Как связь называется со стороны открытой карточки. */
export const LINK_LABEL: Record<string, string> = {
  subtask: 'подзадача', parent: 'родительская',
  blocks: 'блокирует', blocked_by: 'заблокирована',
  relates: 'связана', duplicates: 'дублирует', duplicated_by: 'дублируется',
}

/** Дата в строке списка: «31.08», а в другом году — «31.08.2025».
 *
 *  Год у всех строк одинаковый и потому не различает их, а место занимает на
 *  каждой. Когда он не текущий — печатается: тогда он и есть то, что человек
 *  должен заметить. */
export const dt = (s: string | null) => {
  if (!s) return '—'
  const d = new Date(s)
  if (isNaN(d.getTime())) return '—'
  return d.getFullYear() === new Date().getFullYear()
    ? d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
    : d.toLocaleDateString('ru-RU')
}

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
    // Толчок обязан читаться в следе своим словом: «написал» скрыло бы, что это
    // руководитель напомнил, а через месяц спросят именно об этом.
    case 'nudge': return 'напомнил о работе'
    case 'external_stage': return `этап внешней системы: ${e.to ?? '—'}`
    default: return 'написал'
  }
}

/** Где сейчас мяч — словами, одинаковыми с «Заявками». */
export const WAITING_LABEL: Record<string, string> = {
  external: 'ждём внешнюю сторону', us: 'мяч у нас',
}
