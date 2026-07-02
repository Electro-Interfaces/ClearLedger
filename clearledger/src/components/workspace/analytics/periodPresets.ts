/**
 * Единый источник хелперов дат, пресетов периода и генераторов N периодов
 * для аналитических пикеров (AnalyticsPeriodPicker, PeriodRangePicker,
 * MultiPeriodPicker, WorkspaceFilterModal). Устраняет дубли.
 *
 * Все даты форматируются ЛОКАЛЬНО (isoLocal), а не через toISOString(), —
 * иначе в TZ восточнее UTC границы месяца/года сдвигаются на день назад.
 */

export interface Period {
  from: string  // YYYY-MM-DD
  to: string    // YYYY-MM-DD
}

/** Локальная ISO-дата (без сдвига TZ, в отличие от toISOString). */
export function isoLocal(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function todayISO(): string {
  return isoLocal(new Date())
}

export function daysAgoISO(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoLocal(d)
}

export function monthFirstISO(): string {
  const d = new Date()
  return isoLocal(new Date(d.getFullYear(), d.getMonth(), 1))
}

export function monthLastISO(): string {
  const d = new Date()
  return isoLocal(new Date(d.getFullYear(), d.getMonth() + 1, 0))
}

export function prevMonthBounds(): Period {
  const d = new Date()
  const first = new Date(d.getFullYear(), d.getMonth() - 1, 1)
  const last = new Date(d.getFullYear(), d.getMonth(), 0)
  return { from: isoLocal(first), to: isoLocal(last) }
}

/** Быстрые пресеты для одиночного пикера периода. */
export const PERIOD_PRESETS: { label: string; value: () => Period }[] = [
  { label: '30 дн', value: () => ({ from: daysAgoISO(30), to: todayISO() }) },
  { label: 'Тек. месяц', value: () => ({ from: monthFirstISO(), to: todayISO() }) },
  { label: 'Прошл. месяц', value: prevMonthBounds },
  { label: 'YTD', value: () => ({ from: `${new Date().getFullYear()}-01-01`, to: todayISO() }) },
]

function shiftYear(iso: string, delta: number): string {
  const d = new Date(iso)
  d.setFullYear(d.getFullYear() + delta)
  return isoLocal(d)
}

/** N последних календарных месяцев, заканчивая месяцем anchor.to (старые → новые). */
export function buildMoM(anchor: Period, n = 3): Period[] {
  const base = new Date(anchor.to)
  const y = base.getFullYear(); const m = base.getMonth()
  const out: Period[] = []
  for (let i = n - 1; i >= 0; i--) {
    out.push({
      from: isoLocal(new Date(y, m - i, 1)),
      to: isoLocal(new Date(y, m - i + 1, 0)),
    })
  }
  return out
}

/** N последних кварталов, заканчивая кварталом anchor.to (старые → новые). */
export function buildQoQ(anchor: Period, n = 3): Period[] {
  const base = new Date(anchor.to)
  const q = Math.floor(base.getMonth() / 3)  // 0..3
  const y = base.getFullYear()
  const out: Period[] = []
  for (let i = n - 1; i >= 0; i--) {
    const qStartMonth = q * 3 - i * 3
    out.push({
      from: isoLocal(new Date(y, qStartMonth, 1)),
      to: isoLocal(new Date(y, qStartMonth + 3, 0)),
    })
  }
  return out
}

/** Тот же интервал anchor, сдвинутый на i лет назад (год-к-году; старые → новые). */
export function buildYoY(anchor: Period, n = 2): Period[] {
  const out: Period[] = []
  for (let i = n - 1; i >= 0; i--) {
    out.push({ from: shiftYear(anchor.from, -i), to: shiftYear(anchor.to, -i) })
  }
  return out
}
