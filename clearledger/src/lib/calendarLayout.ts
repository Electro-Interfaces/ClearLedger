import { companyDayStart, companyDayTime, companyTime } from './companyTime'

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

export function layoutDayEvents<T extends TimedEvent>(events: T[], day: Date) {
  const segments = events.flatMap(event => {
    const segment = eventDaySegment(event, day)
    return segment ? [{ event, ...segment, column: 0, columns: 1 }] : []
  }).sort((a, b) => a.start.getTime() - b.start.getTime() || b.end.getTime() - a.end.getTime())
  let group: typeof segments = []
  let groupEnd = 0
  let columns: number[] = []
  const finish = () => { for (const entry of group) entry.columns = columns.length }
  for (const entry of segments) {
    const start = entry.start.getTime()
    const end = entry.end.getTime()
    if (start >= groupEnd) {
      finish()
      group = []
      columns = []
    }
    let column = columns.findIndex(until => until <= start)
    if (column < 0) column = columns.length
    columns[column] = end
    entry.column = column
    group.push(entry)
    groupEnd = Math.max(groupEnd, end)
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
