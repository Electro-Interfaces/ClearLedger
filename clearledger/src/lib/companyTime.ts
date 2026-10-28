/** Единый часовой пояс рабочих календарей компании. */
export const COMPANY_TIME_ZONE = 'Europe/Moscow'

type TimeParts = { year: number; month: number; day: number; hour: number; minute: number; second: number }

const partsFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: COMPANY_TIME_ZONE,
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

function partsOf(value: Date | string): TimeParts {
  const date = value instanceof Date ? value : new Date(value)
  const parts = Object.fromEntries(partsFormatter.formatToParts(date)
    .filter((part) => part.type !== 'literal')
    .map((part) => [part.type, Number(part.value)]))
  return parts as TimeParts
}

/** Ключ даты календарной ячейки: Date здесь может быть локальной полуночью. */
export function calendarDayKey(day: Date): string {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
}

/** Дата, на которую в Москве приходится указанный момент. */
export function companyDateKey(value: Date | string): string {
  const { year, month, day } = partsOf(value)
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

/** Сегодня в календаре как дата без времени, пригодная для date-fns. */
export function companyTodayDate(): Date {
  const [year, month, day] = companyDateKey(new Date()).split('-').map(Number)
  return new Date(year, month - 1, day)
}

/** Преобразует время на часах Москвы в точный момент времени. */
export function companyDateTimeToDate(value: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value)
  if (!match) return new Date(Number.NaN)
  const [, y, mo, d, h, mi] = match.map(Number)
  const target = Date.UTC(y, mo - 1, d, h, mi)
  let candidate = target
  // Находим смещение зоны по IANA, не полагаясь на настройки устройства.
  for (let i = 0; i < 3; i += 1) {
    const actual = partsOf(new Date(candidate))
    const represented = Date.UTC(actual.year, actual.month - 1, actual.day,
      actual.hour, actual.minute, actual.second)
    candidate += target - represented
  }
  return new Date(candidate)
}

export function companyDateTimeToISO(value: string): string {
  return companyDateTimeToDate(value).toISOString()
}

/** Значение для input datetime-local из момента времени в часовом поясе компании. */
export function companyDateTimeInput(value: Date | string): string {
  const { year, month, day, hour, minute } = partsOf(value)
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

export function companyTime(value: Date | string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: COMPANY_TIME_ZONE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(value instanceof Date ? value : new Date(value))
}

export function companyDateTime(value: Date | string, options: Intl.DateTimeFormatOptions = {}): string {
  return new Intl.DateTimeFormat('ru-RU', {
    ...options, timeZone: COMPANY_TIME_ZONE,
  }).format(value instanceof Date ? value : new Date(value))
}

/** Начало календарного дня по Москве, представленное абсолютным временем. */
export function companyDayStart(day: Date): Date {
  return companyDateTimeToDate(`${calendarDayKey(day)}T00:00`)
}

export function companyDayTime(day: Date, hour: number, minute = 0): Date {
  return companyDateTimeToDate(`${calendarDayKey(day)}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`)
}

export function isCompanyToday(day: Date): boolean {
  return calendarDayKey(day) === companyDateKey(new Date())
}

export function isCompanyDay(value: Date | string, day: Date): boolean {
  return companyDateKey(value) === calendarDayKey(day)
}

export function companyMinutesNow(): number {
  const { hour, minute } = partsOf(new Date())
  return hour * 60 + minute
}
