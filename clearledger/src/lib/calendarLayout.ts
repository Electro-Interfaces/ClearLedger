import { companyDayStart, companyDayTime, companyTime } from './companyTime.ts'

type TimedEvent = { id: string; starts_at: string; ends_at: string }

export function eventDaySegment(event: TimedEvent, day: Date) {
  const from = companyDayStart(day)
  const nextDay = new Date(day)
  nextDay.setDate(nextDay.getDate() + 1)
  const to = companyDayStart(nextDay)
  const start = new Date(Math.max(new Date(event.starts_at).getTime(), from.getTime()))
  const end = new Date(Math.min(new Date(event.ends_at).getTime(), to.getTime()))
  if (!(start < end)) return null
  const [startHour, startMinute] = companyTime(start).split(':').map(Number)
  const [endHour, endMinute] = companyTime(end).split(':').map(Number)
  return {
    start, end,
    startMinute: startHour * 60 + startMinute,
    endMinute: end.getTime() === to.getTime() ? 1440 : endHour * 60 + endMinute,
    continues: new Date(event.starts_at) < from,
  }
}

/**
 * Колонки встреч одного дня.
 *
 * `minMinutes` — сколько минут занимает на экране самый короткий блок: встреча,
 * завершённая через десять секунд, рисуется строкой текста, и для пересечений
 * она такой же длины, иначе соседние строки ложатся одна на другую.
 * `span` — сколько колонок встреча занимает вправо: колонки цепочки считаются по
 * самому плотному месту, и без растяжения утренняя встреча делила ширину с
 * вечерними, которых рядом с ней нет (QA 28.10.2026).
 */
export function layoutDayEvents<T extends TimedEvent>(events: T[], day: Date, minMinutes = 0) {
  const minMs = minMinutes * 60_000
  const segments = events.flatMap(event => {
    const segment = eventDaySegment(event, day)
    // `group` — номер цепочки пересекающихся встреч. Нужен тому, кто рисует:
    // на узкой колонке показать все колонки нельзя, и свернуть лишнее в «+N»
    // можно только внутри одной цепочки, а не по дню целиком.
    if (!segment) return []
    const from = segment.start.getTime()
    return [{ event, ...segment, from, to: Math.max(segment.end.getTime(), from + minMs),
      column: 0, columns: 1, span: 1, group: 0 }]
  }).sort((a, b) => a.from - b.from || b.to - a.to)
  let group: typeof segments = []
  let groupEnd = 0
  let groupIndex = 0
  let columns: number[] = []
  const finish = () => {
    for (const entry of group) {
      entry.columns = columns.length
      entry.group = groupIndex
      let span = 1
      while (entry.column + span < columns.length && !group.some(other => other.column === entry.column + span
        && other.from < entry.to && entry.from < other.to)) span += 1
      entry.span = span
    }
    if (group.length) groupIndex += 1
  }
  for (const entry of segments) {
    if (entry.from >= groupEnd) {
      finish()
      group = []
      columns = []
    }
    let column = columns.findIndex(until => until <= entry.from)
    if (column < 0) column = columns.length
    columns[column] = entry.to
    entry.column = column
    group.push(entry)
    groupEnd = Math.max(groupEnd, entry.to)
  }
  finish()
  return segments
}

/**
 * Когда расписание «Трека» поставит дело в этих днях — только будущие моменты:
 * прошедшие уже стали настоящими поручениями со сроком.
 * ponytail: час берётся как местный, `rule.tz` не учитывается — расписание
 * заводят в своём поясе; считать по поясу правила, когда появятся чужие.
 */
export function recurrenceTimes(
  rule: { mode?: string; at?: string; weekday?: number; day?: number },
  days: Date[], after: Date,
) {
  const [hour, minute] = (rule.at ?? '09:00').split(':').map(Number)
  return days
    .filter(day => rule.mode === 'daily'
      || (rule.mode === 'weekly' && (day.getDay() + 6) % 7 === rule.weekday)
      || (rule.mode === 'monthly' && day.getDate() === rule.day))
    .map(day => {
      return companyDayTime(day, hour || 0, minute || 0)
    })
    .filter(at => at > after)
}

/**
 * Новое время встречи, которую тянут мышью: минуты от начала дня.
 *
 * `move` — переносит, сохраняя длительность; `start` и `end` — тянут за край.
 * Шаг — 15 минут по часам дня, а не по сдвигу: встреча с 09:04 встаёт на
 * 09:00 или 09:15, как в настольных календарях. Встреча не выходит за сутки и
 * не становится короче шага.
 */
export function dragTimes(mode: 'move' | 'start' | 'end', start: number, end: number,
  deltaMinutes: number, step = 15) {
  const snap = (m: number) => Math.round(m / step) * step
  if (mode === 'move') {
    const length = Math.max(end - start, step)
    const from = Math.min(Math.max(snap(start + deltaMinutes), 0), 1440 - length)
    return { start: from, end: from + length }
  }
  if (mode === 'start') return { start: Math.min(Math.max(snap(start + deltaMinutes), 0), end - step), end }
  return { start, end: Math.max(Math.min(snap(end + deltaMinutes), 1440), start + step) }
}
