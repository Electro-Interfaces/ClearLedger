/**
 * Разбор даты и времени, набранных РУКАМИ.
 *
 * Отдельным модулем от компонента (`components/ui/date-time-field.tsx`), потому что
 * ошибка здесь не падает, а тихо ставит встречу не на тот день: «31.02» превращается в
 * 3 марта, «26» в 1926 год, «930» в 93 часа. Такое ловится только тестом.
 *
 * Разбор намеренно прощающий: разделители не обязательны, год и минуты — тоже. На
 * телефоне точка и двоеточие живут на второй раскладке, и требовать их значит просить
 * человека сделать три лишних нажатия ради формы, которую мы и так понимаем.
 */

/** `2026-09-17` → `17.09.2026`. Пустое остаётся пустым, а не «01.01.1970». */
export function dateToText(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '')
  return m ? `${m[3]}.${m[2]}.${m[1]}` : ''
}

/**
 * Текст → `YYYY-MM-DD`, либо null, пока введено не всё.
 *
 * Год из двух цифр читаем как 20xx: встреч 1926 года в рабочем календаре не бывает, а
 * набрать «26» вместо «2026» человек пытается постоянно.
 */
export function textToDate(text: string, base = new Date()): string | null {
  const d = (text || '').replace(/\D/g, '')
  if (d.length < 4) return null
  const day = Number(d.slice(0, 2))
  const month = Number(d.slice(2, 4))
  let year = base.getFullYear()
  if (d.length >= 8) year = Number(d.slice(4, 8))
  else if (d.length >= 6) year = 2000 + Number(d.slice(4, 6))
  if (!day || !month || month > 12 || day > 31) return null
  const dt = new Date(year, month - 1, day)
  // 31.02 существует только в арифметике Date — молча уехавшая дата хуже отказа.
  if (dt.getDate() !== day || dt.getMonth() !== month - 1) return null
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

/** Текст → `HH:mm`. `930` → 09:30, `9` → 09:00, `1745` → 17:45. */
export function textToTime(text: string): string | null {
  const d = (text || '').replace(/\D/g, '')
  if (!d) return null
  let h: number, m: number
  if (d.length <= 2) { h = Number(d); m = 0 }
  else if (d.length === 3) { h = Number(d.slice(0, 1)); m = Number(d.slice(1)) }
  else { h = Number(d.slice(0, 2)); m = Number(d.slice(2, 4)) }
  if (h > 23 || m > 59) return null
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
