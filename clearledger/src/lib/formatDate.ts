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

/** Месяцы в именительном («май 26»); родительный («30 мая») — внутри formatPeriod.
 *  Экспортирован, чтобы экраны со своим форматом подписи не заводили свою копию
 *  массива: их набралось десять, и они успели разойтись в падеже и в индексации. */
export const MONTHS_SHORT_NOM = MONTHS_SHORT.map((m, i) => (i === 4 ? 'май' : m))
const MONTHS_NOM = MONTHS_SHORT_NOM

/** Подпись бакета на оси графика: «2026-01» → «янв 26», «2026-07-15» → «15 июл».
 *  ISO-дату на оси не показываем — по той же причине, что и в шапке фильтра. */
export function formatBucket(bucket: string): string {
  const [y, m, d] = bucket.split('-')
  const i = Number(m) - 1
  if (!MONTHS_SHORT[i]) return bucket
  // «1 мая» — родительный при числе, «май 26» — именительный, когда месяц сам по себе.
  return d ? `${Number(d)} ${MONTHS_SHORT[i]}` : `${MONTHS_NOM[i]} ${y.slice(2)}`
}

/** «сен 2025» — месяц с ПОЛНЫМ годом.
 *
 *  Отличается от `formatBucket` («сен 25») намеренно и нужен там, где ряд
 *  пересекает границу года: на оси в 10 px «сен 25» и «сен 26» различаются одной
 *  цифрой, и руководитель заказчика прямо сказал, что не понимает, какой это год
 *  (замечание от 18.08.2026). Там, где ряд заведомо внутри одного года, короткая
 *  форма лучше — она не съедает ширину оси. */
export function formatMonth(iso: string): string {
  const [y, m] = iso.split('-')
  const i = Number(m) - 1
  if (!MONTHS_SHORT_NOM[i] || !y) return iso
  return `${MONTHS_SHORT_NOM[i]} ${y}`
}

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
