/** Пустая строка — тип ещё не выбирали, `none` — осознанно без типа. */
export function selectedTaskType(selection: string, defaultType: string): string {
  return selection === 'none' ? '' : selection || defaultType
}

/** День поля date в календаре браузера. UTC-момент хранения не изменяется. */
export function taskDueDay(value: string | null | undefined): string {
  if (!value) return ''
  // Старые значения без времени уже представляют календарный день.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Сокрытие ограничивается местным днём срока, а не его UTC-датой. */
export function clampTaskDefer(day: string, dueAt: string | null | undefined): string {
  const due = taskDueDay(dueAt)
  return due && day > due ? due : day
}
