type TimedEvent = { id: string; starts_at: string; ends_at: string }

export function eventDaySegment(event: TimedEvent, day: Date) {
  const from = new Date(day)
  from.setHours(0, 0, 0, 0)
  const to = new Date(from)
  to.setDate(to.getDate() + 1)
  const start = new Date(Math.max(new Date(event.starts_at).getTime(), from.getTime()))
  const end = new Date(Math.min(new Date(event.ends_at).getTime(), to.getTime()))
  if (!(start < end)) return null
  return {
    start, end,
    startMinute: start.getHours() * 60 + start.getMinutes(),
    endMinute: end.getTime() === to.getTime() ? 1440 : end.getHours() * 60 + end.getMinutes(),
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
