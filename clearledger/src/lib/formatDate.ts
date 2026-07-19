/** Формат даты (DD.MM.YYYY) */
export function formatDate(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString('ru-RU')
}

/** Формат даты + времени */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Только время */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

/** «30 июн – 17 июл 2026» — месяц словом, год один раз (или у каждой даты, если разные).
 *  Единый формат периода для шапки фильтра и подписей внутри панелей: ISO-даты
 *  в интерфейсе не показываем. */
export function formatPeriod(fromIso: string, toIso: string): string {
  const [fy, fm, fd] = fromIso.split('-').map(Number)
  const [ty, tm, td] = toIso.split('-').map(Number)
  if (!fd || !td) return `${fromIso} – ${toIso}`
  const from = `${fd} ${MONTHS_SHORT[fm - 1]}`
  const to = `${td} ${MONTHS_SHORT[tm - 1]}`
  return fy === ty ? `${from} – ${to} ${ty}` : `${from} ${fy} – ${to} ${ty}`
}
