/**
 * Диаграмма Ганта проекта — общая отрисовка для интеграции и проектов станций.
 *
 * Плановых дат в проектах нет, поэтому шкала делится на две зоны. Слева — ФАКТ:
 * полосы от входа в стадию до выхода из неё (у текущей — до сейчас), шкала растянута
 * ровно на прожитое время и известные даты (у молодого проекта — по часам), без пустых
 * недель. Справа — «впереди»: оставшиеся стадии лесенкой в порядке маршрута, равными
 * долями и без дат — очередь, а не прогноз. Ромбы — события с датой: подтверждённый
 * пункт, срок или факт параллельного трека.
 *
 * Данные строки собирает вызывающий: интеграция — из журнала маршрута и чек-листа,
 * станция — из истории смен стадии и треков «Пути проекта».
 */
import type { ReactNode } from 'react'
import { H, DAY, ruDate, hm, dur } from './ganttTime'

export type GanttState = 'done' | 'current' | 'stopped' | 'future' | 'track'
export interface GanttMark { key: string; at: number; title: string; cls?: string }
export interface GanttRow {
  key: string
  label: string
  /** Строка под названием: даты, длительность, пункты. */
  sub: string
  state: GanttState
  /** Отрезки на стадии: возврат на доработку даёт второй отрезок той же строки. */
  segments: { start: number; end: number }[]
  marks?: GanttMark[]
  /** Место в очереди «впереди» (0 — продолжение текущей), подсказка к нему. */
  slot?: number
  slotTitle?: string
  onOpen?: () => void
}
export interface GanttGroup { key: string; label: string; rows: GanttRow[] }

/** Шаги шкалы: берём первый, при котором делений в зоне факта не больше 12. */
const STEPS = [H, 2 * H, 3 * H, 6 * H, 12 * H, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY]
const dayStart = (t: number) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime() }
/** Доля ширины под «впереди», если есть очередь. */
const AHEAD = 0.32
const BAR: Partial<Record<GanttState, string>> = { done: 'bg-emerald-500', current: 'bg-primary', stopped: 'bg-amber-500' }

/** `now` — момент отрисовки, его держит вызывающий (тот же, что у полос «до сейчас»). */
export function GanttChart({ groups, legend, now }: { groups: GanttGroup[]; legend: ReactNode; now: number }) {
  const rows = groups.flatMap((g) => g.rows)
  const times = rows.flatMap((r) => [...r.segments.flatMap((s) => [s.start, s.end]), ...(r.marks ?? []).map((m) => m.at)])
  const t0 = Math.min(...(times.length ? times : [now - DAY]), now)
  const t1 = Math.max(...times, now)
  const pad = Math.max((t1 - t0) * 0.04, 0.5 * H)
  const from = t0 - pad
  const to = t1 + pad
  const slots = Math.max(0, ...rows.map((r) => (r.slot ?? -1) + 1))
  const ahead = slots > 0 ? AHEAD : 0
  const past = 1 - ahead
  const span = to - from
  const x = (t: number) => ((t - from) / span) * past * 100
  const pct = (t: number) => `${x(t)}%`
  const slotW = slots ? (ahead * 100) / slots : 0

  const step = STEPS.find((s) => span / s <= 12) ?? 30 * DAY
  const ticks: { t: number; label: string; strong: boolean }[] = []
  if (step >= 30 * DAY) {
    const d = new Date(from); d.setDate(1); d.setHours(0, 0, 0, 0); d.setMonth(d.getMonth() + 1)
    for (; d.getTime() <= to; d.setMonth(d.getMonth() + 1)) ticks.push({ t: d.getTime(), label: d.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }), strong: true })
  } else {
    let t = step < DAY ? dayStart(from) + Math.ceil((from - dayStart(from)) / step) * step : dayStart(from) + DAY
    if (step === 7 * DAY || step === 14 * DAY) while (new Date(t).getDay() !== 1) t += DAY
    for (; t <= to; t += step) {
      const midnight = t === dayStart(t)
      ticks.push({ t, label: step < DAY ? (midnight ? ruDate(t) : hm(t)) : ruDate(t), strong: midnight })
    }
  }

  // Фон дорожки: сетка делений, зона «впереди» и линия «сейчас» — одинаковые у всех строк.
  const lane = (children: ReactNode, h = 'min-h-[52px]') => (
    <div className={`relative ${h}`}>
      {ticks.map((k) => <div key={k.t} className={`pointer-events-none absolute inset-y-0 w-px ${k.strong ? 'bg-border' : 'bg-border/40'}`} style={{ left: pct(k.t) }} />)}
      {ahead > 0 && <div className="pointer-events-none absolute inset-y-0 right-0 bg-muted/30" style={{ left: `${past * 100}%` }} />}
      <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-red-500/80" style={{ left: pct(now) }} />
      {children}
    </div>
  )

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-lg border">
        <div className="min-w-[760px]">
          <div className="grid grid-cols-[240px_1fr] border-b bg-muted/40 text-[11px] text-muted-foreground">
            <div className="px-3 py-2 font-medium">Стадия</div>
            <div className="relative h-9">
              {ticks.filter((k) => Math.abs(x(k.t) - x(now)) > 3).map((k) => (
                <span key={k.t} className={`absolute top-1 -translate-x-1/2 whitespace-nowrap ${k.strong ? 'font-medium text-foreground' : ''}`} style={{ left: pct(k.t) }}>{k.label}</span>
              ))}
              <span className="absolute bottom-0.5 -translate-x-1/2 whitespace-nowrap rounded bg-red-500 px-1.5 text-[10px] font-medium text-white" style={{ left: pct(now) }}>сейчас · {ruDate(now)} {hm(now)}</span>
              {ahead > 0 && <span className="absolute top-1 right-0 text-center uppercase tracking-wide" style={{ left: `${past * 100}%` }}>впереди · сроков нет</span>}
            </div>
          </div>
          {groups.map((g) => {
            const segs = g.rows.filter((r) => r.state !== 'track').flatMap((r) => r.segments)
            const queued = g.rows.map((r) => r.slot).filter((s): s is number => s != null)
            return (
              <div key={g.key}>
                <div className="grid grid-cols-[240px_1fr] border-b bg-muted/20">
                  <div className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{g.label}</div>
                  {lane(<>
                    {segs.length > 0 && (() => {
                      const a = Math.min(...segs.map((s) => s.start)); const b = Math.max(...segs.map((s) => s.end))
                      return <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded bg-foreground/40" style={{ left: pct(a), width: `max(3px, calc(${pct(b)} - ${pct(a)}))` }} />
                    })()}
                    {queued.length > 0 && (
                      <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded border border-dashed border-foreground/30"
                        style={{ left: `${past * 100 + Math.min(...queued) * slotW}%`, width: `${(Math.max(...queued) - Math.min(...queued) + 1) * slotW}%` }} />
                    )}
                  </>, 'min-h-7')}
                </div>
                {g.rows.map((r) => (
                  // Вся строка — и название, и полоса — открывает работу стадии.
                  <div key={r.key} onClick={r.onOpen} title={r.onOpen ? 'Открыть работу стадии' : undefined}
                    className={`grid grid-cols-[240px_1fr] border-b last:border-b-0 hover:bg-muted/40 ${r.onOpen ? 'cursor-pointer' : ''}`}>
                    <div className="px-3 py-2 text-left text-sm">
                      <div className={r.state === 'future' ? 'text-muted-foreground' : r.state === 'current' ? 'font-semibold' : r.state === 'track' ? 'text-[13px]' : ''}>{r.label}</div>
                      <div className="text-[11px] text-muted-foreground">{r.sub}</div>
                    </div>
                    {lane(<>
                      {r.segments.map((s, i) => {
                        const len = s.end - s.start
                        return (
                          <div key={i} className={`absolute top-1/2 flex h-6 -translate-y-1/2 items-center overflow-hidden rounded px-1.5 text-[11px] font-medium text-white ${BAR[r.state] ?? 'bg-muted-foreground'}`}
                            style={{ left: pct(s.start), width: `max(6px, calc(${pct(s.end)} - ${pct(s.start)}))` }}
                            title={`${r.label}: ${ruDate(s.start)} ${hm(s.start)} — ${r.state === 'current' && s.end >= now - 60_000 ? 'сейчас' : `${ruDate(s.end)} ${hm(s.end)}`}`}>
                            {x(s.end) - x(s.start) > 5 && <span className="truncate">{dur(len)}</span>}
                          </div>
                        )
                      })}
                      {r.slot != null && (
                        <div className={`absolute top-1/2 h-6 -translate-y-1/2 rounded border border-dashed ${r.state === 'future' ? 'border-muted-foreground/40' : 'border-primary/60 bg-primary/10'}`}
                          style={{ left: `calc(${past * 100 + r.slot * slotW}% + 2px)`, width: `calc(${slotW}% - 4px)` }} title={r.slotTitle} />
                      )}
                      {(r.marks ?? []).map((m) => (
                        <span key={m.key} className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-background shadow ${m.cls ?? 'bg-white'}`}
                          style={{ left: pct(m.at) }} title={m.title} />
                      ))}
                    </>)}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{legend}</p>
    </div>
  )
}
