/** Пустая строка — тип ещё не выбирали, `none` — осознанно без типа. */
export function selectedTaskType(selection: string, defaultType: string): string {
  return selection === 'none' ? '' : selection || defaultType
}

/** День поля date в календаре браузера. UTC-момент хранения не изменяется. */
export function taskDueDay(value: string | null | undefined, timeZone?: string): string {
  if (!value) return ''
  // Старые значения без времени уже представляют календарный день.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  if (timeZone) {
    // Для личного ограничения берём тот же пояс профиля, что и сервер.
    let formatter: Intl.DateTimeFormat
    try {
      formatter = new Intl.DateTimeFormat('en-CA', {
        timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
      })
    } catch {
      formatter = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit',
      })
    }
    const parts = formatter.formatToParts(date)
    const part = (type: string) => parts.find((p) => p.type === type)?.value
    return `${part('year')}-${part('month')}-${part('day')}`
  }
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Сокрытие ограничивается местным днём срока, а не его UTC-датой. */
export function clampTaskDefer(day: string, dueAt: string | null | undefined, timeZone?: string): string {
  const due = taskDueDay(dueAt, timeZone)
  return due && day > due ? due : day
}
