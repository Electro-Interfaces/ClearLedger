/** Дополнительная проверка ссылки на клиенте; основной allowlist остаётся у API. */
export function safeManagementHref(value: string): string | null {
  if (!value || value !== value.trim() || [...value].some((char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127 || char === '\\')) return null
  if (value.startsWith('//')) return null
  if (!/^[a-z][a-z\d+.-]*:/i.test(value)) return value
  try {
    const url = new URL(value)
    return (url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password
      ? url.href : null
  } catch { return null }
}

export function managementTimeZone(preferred?: string): string {
  if (preferred) {
    try { new Intl.DateTimeFormat('ru', { timeZone: preferred }); return preferred } catch { /* неверная зона */ }
  }
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

export function managementDateTimestamp(value?: string | null): number {
  if (!value) return Number.POSITIVE_INFINITY
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value)
  // API отдаёт UTC; наивный ISO timestamp также интерпретируем как UTC, а не часовой пояс ПК.
  const iso = !dateOnly && !/(Z|[+-]\d\d:?\d\d)$/i.test(value) ? `${value}Z` : value
  const at = Date.parse(iso)
  return Number.isNaN(at) ? Number.POSITIVE_INFINITY : at
}

export function managementDate(value?: string | null, timeZone = 'UTC'): string {
  const at = managementDateTimestamp(value)
  if (!Number.isFinite(at)) return 'не указано'
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value!)
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: dateOnly ? 'UTC' : timeZone,
    day: 'numeric', month: 'short', year: 'numeric',
    ...(dateOnly ? {} : { hour: '2-digit', minute: '2-digit' }),
  }).format(at)
}

export function initialManagementPeriod(timeZone: string) {
  const now = new Date()
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now)
  const part = (type: string) => parts.find((p) => p.type === type)!.value
  const from = `${part('year')}-${part('month')}-${part('day')}`
  const end = new Date(`${from}T00:00:00Z`)
  end.setUTCDate(end.getUTCDate() + 6)
  return { from, to: end.toISOString().slice(0, 10) }
}

export function validManagementPeriod(from: string, to: string): boolean {
  const valid = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value)
    && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
  return valid(from) && valid(to) && from <= to
}

const MANAGEMENT_STATUS: Record<string, Record<string, string>> = {
  chats: { group: 'Группа', direct: 'Личный чат', channel: 'Канал' },
  tasks: { open: 'В работе', done: 'Выполнена', cancelled: 'Отменена' },
  calendar: { planned: 'Запланирована', cancelled: 'Отменена', poll: 'Согласование времени' },
}
export function managementStatusLabel(kind: string, value?: string | null): string | null {
  if (!value) return null
  // Незнакомый внутренний код не выдаём за понятный пользователю статус.
  return MANAGEMENT_STATUS[kind]?.[value] ?? null
}
