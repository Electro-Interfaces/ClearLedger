/**
 * Сложение показателей узла по строкам ряда — для таблиц «по темам», «по КЦ» и
 * графика по времени, где узел отдаёт несколько строк на одну группу (интервалы,
 * разрез «кем обслужен»).
 *
 * Счётчики складываются; доли пересчитываются из счётчиков теми же формулами, что
 * у узла (node/src/stats.ts, DEFINITIONS); среднее ожидание взвешивается числом
 * отвеченных — у узла оно и есть сумма ожиданий на число отвеченных.
 */
import type { Metrics, SeriesRow } from '@/services/voiceService'

const СЧЁТЧИКИ = [
  'arrived', 'afterHours', 'offered', 'transferredIn', 'answered', 'answeredInSl', 'abandoned', 'abandonedShort', 'fallback',
  'callbackOffered', 'callbackAccepted', 'callbackCreated', 'callbackExecuted', 'callbackReached', 'callbackOverdue',
  'transferred', 'repeatCallers', 'noDisposition',
] as const

const доля = (a: number, b: number) => (b > 0 ? Math.round((a / b) * 1000) / 10 : null)

export function сложить(строки: Metrics[]): Metrics {
  const m: Metrics = {}
  for (const k of СЧЁТЧИКИ) m[k] = строки.reduce((s, r) => s + (r[k] ?? 0), 0)
  const отв = m.answered ?? 0
  const ожидание = строки.reduce((s, r) => s + (r.asaSec ?? 0) * (r.answered ?? 0), 0)
  const коротко = m.abandonedShort ?? 0
  m.slPct = доля(m.answeredInSl ?? 0, (m.offered ?? 0) - коротко)
  m.asaSec = отв > 0 ? Math.round(ожидание / отв) : null
  m.abandonPct = доля((m.abandoned ?? 0) - коротко, (m.offered ?? 0) - коротко)
  m.fallbackPct = доля(m.fallback ?? 0, m.offered ?? 0)
  m.transferPct = доля(m.transferred ?? 0, отв)
  m.fcrPct = отв > 0 ? доля(отв - (m.repeatCallers ?? 0), отв) : null
  m.waitMaxSec = строки.reduce<number | null>((s, r) => (r.waitMaxSec == null ? s : Math.max(s ?? 0, r.waitMaxSec)), null)
  return m
}

/** Строки ряда по ключу группы; `фильтр` — оставить только нужные (например, обслуженные КЦ). */
export function поГруппам(rows: SeriesRow[], ключ: string, фильтр?: (r: SeriesRow) => boolean) {
  const группы = new Map<string, Metrics[]>()
  for (const r of rows) {
    if (фильтр && !фильтр(r)) continue
    const g = r.group?.[ключ] ?? ''
    группы.set(g, [...(группы.get(g) ?? []), r.metrics])
  }
  return [...группы.entries()].map(([g, ms]) => ({ группа: g, m: сложить(ms) }))
}

/** Строки ряда по началу интервала. */
export function поВремени(rows: SeriesRow[], фильтр?: (r: SeriesRow) => boolean) {
  const t = new Map<string, Metrics[]>()
  for (const r of rows) {
    if (фильтр && !фильтр(r)) continue
    t.set(r.start, [...(t.get(r.start) ?? []), r.metrics])
  }
  return [...t.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([start, ms]) => ({ start, m: сложить(ms) }))
}

/**
 * «Куда ушли звонки» из сводки: части, которые не пересекаются (как считает узел).
 * Остаток — положили трубку до очереди или звонок ещё идёт.
 *
 * Перевод на другую линию узел считает новым отрезком: прежний отрезок — отвеченный
 * и переведённый, новый входит в «поставлено» и в transferredIn и несёт свой исход.
 * Поэтому судьбу звонка решает последний отрезок: из переведённых вычитаются переводы
 * на линию (их столько же, сколько transferredIn), иначе такой звонок встал бы дважды.
 */
export function кудаУшли(m: Metrics) {
  const части = [
    { key: 'answered', имя: 'Отвечено', n: Math.max(0, (m.answered ?? 0) - (m.transferred ?? 0)), цвет: 'bg-chart-1' },
    { key: 'transferred', имя: 'Переведён сотруднику', n: Math.max(0, (m.transferred ?? 0) - (m.transferredIn ?? 0)), цвет: 'bg-chart-2' },
    { key: 'callback', имя: 'Выбрал обратный звонок', n: m.callbackAccepted ?? 0, цвет: 'bg-chart-4' },
    { key: 'fallback', имя: 'Запасной сценарий', n: m.fallback ?? 0, цвет: 'bg-chart-5' },
    { key: 'abandoned', имя: 'Брошен в очереди', n: m.abandoned ?? 0, цвет: 'bg-chart-3' },
    { key: 'afterHours', имя: 'Вне часов приёма', n: m.afterHours ?? 0, цвет: 'bg-muted-foreground/60' },
  ]
  const учтено = части.reduce((s, x) => s + x.n, 0)
  const остаток = Math.max(0, (m.arrived ?? 0) - учтено)
  if (остаток) части.push({ key: 'other', имя: 'До очереди не дошёл или идёт', n: остаток, цвет: 'bg-border' })
  return части
}
