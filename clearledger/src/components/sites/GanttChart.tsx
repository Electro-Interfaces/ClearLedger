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
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import { H, DAY, ruDate, hm, dur } from './ganttTime'

export type GanttState = 'done' | 'current' | 'stopped' | 'future' | 'track'
export interface GanttMark { key: string; at: number; title: string; cls?: string }
export interface GanttRow {
  key: string
  label: string
  /** Строка под названием: даты, длительность, пункты. */
  sub: string
  state: GanttState
  /** Отрезки на стадии: возврат на доработку даёт второй отрезок той же строки.
   *  `dashed` — ещё идёт и не закрыто (открытый пункт текущей стадии). */
  segments: { start: number; end: number; dashed?: boolean }[]
  marks?: GanttMark[]
  /** Место в очереди «впереди» (0 — продолжение текущей), подсказка к нему. */
  slot?: number
  slotTitle?: string
  onOpen?: () => void
  /** Подэтапы: пункты чек-листа стадии. `required` — критичный (держит переход). */
  children?: GanttRow[]
  required?: boolean
  /** Пункт: выполнен, открыт, обязательность снята, данные изменились — подтвердить заново. */
  status?: 'done' | 'open' | 'waived' | 'reconfirm'
  /** Пункт держит переход сейчас. */
  blocking?: boolean
  /** Норматив стадии по регламенту, мс: полоса сверх него красная. */
  normMs?: number
}

type Scale = 'fit' | 'hour' | 'day' | 'week' | 'month'
/** Шаг и ширина деления фиксированного масштаба; «весь проект» — шаг подбирается под ширину. */
const SCALES: { k: Scale; label: string; step?: number; px?: number; max?: number }[] = [
  { k: 'fit', label: 'Весь проект' },
  { k: 'hour', label: 'Часы', step: H, px: 44, max: 7 * DAY },
  { k: 'day', label: 'Дни', step: DAY, px: 34, max: 400 * DAY },
  { k: 'week', label: 'Недели', step: 7 * DAY, px: 64 },
  { k: 'month', label: 'Месяцы', step: 30 * DAY, px: 90 },
]

type Filter = 'all' | 'blocking' | 'overdue' | 'open' | 'reconfirm' | 'waived'
const FILTERS: { k: Filter; label: string; hint: string }[] = [
  { k: 'all', label: 'Все', hint: 'Все стадии' },
  { k: 'blocking', label: 'Держит переход', hint: 'Открытые критичные пункты текущей стадии и пункты, которые надо подтвердить заново' },
  { k: 'overdue', label: 'Сверх норматива', hint: 'Стадии, на которых проект стоит дольше срока регламента' },
  { k: 'open', label: 'Не выполнено', hint: 'Невыполненные пункты пройденных и текущей стадий' },
  { k: 'reconfirm', label: 'Подтвердить заново', hint: 'Данные изменились после подтверждения' },
  { k: 'waived', label: 'Снята обязательность', hint: 'Критичные пункты, пропущенные под ответственность' },
]
const spent = (r: GanttRow) => r.segments.filter((s) => !s.dashed).reduce((a, s) => a + (s.end - s.start), 0)
const overdue = (r: GanttRow) => r.normMs != null && r.state !== 'future' && spent(r) > r.normMs
const itemMatch = (c: GanttRow, f: Filter, parent: GanttRow) =>
  f === 'blocking' ? !!c.blocking
    : f === 'open' ? c.status === 'open' && parent.state !== 'future'
      : f === 'reconfirm' ? c.status === 'reconfirm'
        : f === 'waived' ? c.status === 'waived' : false
export interface GanttGroup { key: string; label: string; rows: GanttRow[] }

/** Шаги шкалы: берём первый, при котором делений в зоне факта не больше 12. */
const STEPS = [H, 2 * H, 3 * H, 6 * H, 12 * H, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY]
const dayStart = (t: number) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime() }
/** Доля ширины под «впереди», если есть очередь. */
const AHEAD = 0.32
const BAR: Partial<Record<GanttState, string>> = { done: 'bg-emerald-500', current: 'bg-primary', stopped: 'bg-amber-500' }

/** `now` — момент отрисовки, его держит вызывающий (тот же, что у полос «до сейчас»). */
export function GanttChart({ groups, legend, now }: { groups: GanttGroup[]; legend: ReactNode; now: number }) {
  // Раскрытые стадии и «все пункты» вместо одних критичных.
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [allItems, setAllItems] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [scale, setScale] = useState<Scale>('fit')
  const box = useRef<HTMLDivElement>(null)
  // Фиксированный масштаб шире экрана — открыть на «сейчас», а не на начале проекта.
  const nowFrac = useRef(0)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const lane = el.scrollWidth - 240
    el.scrollLeft = scale === 'fit' ? 0 : Math.max(0, 240 + lane * nowFrac.current - el.clientWidth * 0.7)
  }, [scale])
  const stageRows = groups.flatMap((g) => g.rows).filter((r) => r.state !== 'track')
  const count = (f: Filter) => f === 'all' ? stageRows.length
    : f === 'overdue' ? stageRows.filter(overdue).length
      : stageRows.reduce((a, r) => a + (r.children ?? []).filter((c) => itemMatch(c, f, r)).length, 0)
  const hasNorm = stageRows.some((r) => r.normMs != null)
  const shownChildren = (r: GanttRow) => filter === 'all' || filter === 'overdue'
    ? (open.has(r.key) ? (r.children ?? []).filter((c) => allItems || c.required) : [])
    : (r.children ?? []).filter((c) => itemMatch(c, filter, r))
  const shownRows = (rows: GanttRow[]) => filter === 'all' ? rows
    : filter === 'overdue' ? rows.filter(overdue)
      : rows.filter((r) => (r.children ?? []).some((c) => itemMatch(c, filter, r)))
  const parents = groups.flatMap((g) => g.rows).filter((r) => r.children?.length)
  const rows = groups.flatMap((g) => g.rows.flatMap((r) => [r, ...(r.children ?? [])]))
  const times = rows.flatMap((r) => [...r.segments.flatMap((s) => [s.start, s.end]), ...(r.marks ?? []).map((m) => m.at)])
  const t0 = Math.min(...(times.length ? times : [now - DAY]), now)
  // Будущая дата (срок договора через полгода) не растягивает шкалу: иначе месяцы
  // факта сжимаются в полоску у края (проверка на «Томилино» 07.10.2026). Вперёд —
  // не дальше четверти прожитого, дальние даты — стрелкой у края с подписью.
  const reach = now + Math.max((now - t0) * 0.25, DAY)
  const t1 = Math.max(...times.filter((t) => t <= reach), now)
  const pad = Math.max((t1 - t0) * 0.04, 0.5 * H)
  const from = t0 - pad
  const to = t1 + pad
  const slots = Math.max(0, ...rows.map((r) => (r.slot ?? -1) + 1))
  const fixed = SCALES.find((s) => s.k === scale && s.step)
  // Фиксированный масштаб: факт — делений × ширина деления, «впереди» — постоянные 360 px
  // (доля от огромной ширины растягивала очередь на полэкрана, проверка 07.10.2026).
  const factPx = fixed ? Math.max(400, ((to - from) / fixed.step!) * fixed.px!) : 0
  const aheadPx = slots > 0 ? 360 : 0
  const ahead = fixed ? aheadPx / (factPx + aheadPx) : slots > 0 ? AHEAD : 0
  const past = 1 - ahead
  const span = to - from
  const x = (t: number) => ((t - from) / span) * past * 100
  const pct = (t: number) => `${x(t)}%`
  nowFrac.current = x(now) / 100
  const slotW = slots ? (ahead * 100) / slots : 0

  const step = fixed?.step ?? STEPS.find((s) => span / s <= 12) ?? 30 * DAY
  // Ширина дорожки в фиксированном масштабе: делений × ширина деления; зона «впереди» — сверху.
  const lanePx = fixed ? factPx + aheadPx : 520
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

  const toggle = (key: string) => setOpen((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n })
  const SUB_BAR: Partial<Record<GanttState, string>> = { done: 'bg-emerald-500/80', current: 'bg-primary/70', stopped: 'bg-amber-500/80' }
  const renderRow = (r: GanttRow, sub = false) => (
    // Вся строка — и название, и полоса — открывает работу стадии.
    <div key={r.key} onClick={r.onOpen} title={r.onOpen ? (sub ? 'Открыть пункт в работе стадии' : 'Открыть работу стадии') : undefined}
      className={`grid grid-cols-[240px_1fr] border-b last:border-b-0 hover:bg-muted/40 ${r.onOpen ? 'cursor-pointer' : ''} ${sub ? 'bg-muted/10' : ''}`}>
      <div className={`sticky left-0 z-10 flex items-start gap-1 border-r bg-card text-left ${sub ? 'py-1 pl-7 pr-2' : 'px-3 py-2'}`}>
        {!sub && (r.children?.length && (filter === 'all' || filter === 'overdue')
          ? <button type="button" aria-label={open.has(r.key) ? 'Свернуть подэтапы' : 'Раскрыть подэтапы'} aria-expanded={open.has(r.key)}
              onClick={(e) => { e.stopPropagation(); toggle(r.key) }}
              className="-ml-1 mt-0.5 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground">
              <ChevronRight className={`h-3.5 w-3.5 transition-transform ${open.has(r.key) ? 'rotate-90' : ''}`} />
            </button>
          : <span className="w-4.5 shrink-0" />)}
        <div className="min-w-0 flex-1">
          <div title={sub ? r.label : undefined} className={sub ? `truncate text-xs ${r.state === 'done' ? '' : 'text-muted-foreground'}` : `text-sm ${r.state === 'future' ? 'text-muted-foreground' : r.state === 'current' ? 'font-semibold' : r.state === 'track' ? 'text-[13px]' : ''}`}>
            {sub && r.required && <span className="mr-1 text-primary" title="Критичный: держит переход">●</span>}{r.label}
          </div>
          <div className={`text-[11px] text-muted-foreground ${sub ? 'truncate' : ''}`} title={sub ? r.sub : undefined}>{r.sub}
            {!sub && overdue(r) && <span className="ml-1 rounded bg-red-500/15 px-1 text-red-600 dark:text-red-400">сверх норматива на {dur(spent(r) - r.normMs!)}</span>}
            {sub && r.blocking && <span className="ml-1 rounded bg-amber-500/15 px-1 text-amber-700 dark:text-amber-400">держит переход</span>}
          </div>
        </div>
      </div>
      {lane(<>
        {r.segments.map((s, i) => {
          const len = s.end - s.start
          return s.dashed
            ? <div key={i} className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded border border-dashed border-primary/60 bg-primary/10"
                style={{ left: pct(s.start), width: `max(6px, calc(${pct(s.end)} - ${pct(s.start)}))` }} title={`${r.label}: открыт с ${ruDate(s.start)}`} />
            : <div key={i} className={`absolute top-1/2 flex -translate-y-1/2 items-center overflow-hidden rounded px-1.5 text-[11px] font-medium text-white ${sub ? `h-2.5 ${SUB_BAR[r.state] ?? 'bg-muted-foreground/60'}` : `h-6 ${BAR[r.state] ?? 'bg-muted-foreground'}`}`}
                style={{ left: pct(s.start), width: `max(${sub ? 3 : 6}px, calc(${pct(s.end)} - ${pct(s.start)}))` }}
                title={`${r.label}: ${ruDate(s.start)} ${hm(s.start)} — ${r.state === 'current' && s.end >= now - 60_000 ? 'сейчас' : `${ruDate(s.end)} ${hm(s.end)}`}`}>
                {!sub && x(s.end) - x(s.start) > 5 && <span className="truncate">{dur(len)}</span>}
              </div>
        })}
        {!sub && r.normMs != null && r.segments.length > 0 && r.state !== 'future' && (() => {
          const start = r.segments[0].start
          const limit = start + r.normMs
          const end = Math.max(...r.segments.map((s) => s.end))
          return <>
            {limit <= to && <div className="pointer-events-none absolute top-1 bottom-1 w-0 border-l-2 border-dashed border-red-500/70" style={{ left: pct(limit) }} title={`Норматив стадии: до ${ruDate(limit)}`} />}
            {overdue(r) && end > limit && <div className="pointer-events-none absolute top-1/2 h-6 -translate-y-1/2 rounded-r bg-red-500/70" style={{ left: pct(limit), width: `calc(${pct(end)} - ${pct(limit)})` }} />}
          </>
        })()}
        {r.slot != null && (
          <div className={`absolute top-1/2 h-6 -translate-y-1/2 rounded border border-dashed ${r.state === 'future' ? 'border-muted-foreground/40' : 'border-primary/60 bg-primary/10'}`}
            style={{ left: `calc(${past * 100 + r.slot * slotW}% + 2px)`, width: `calc(${slotW}% - 4px)` }} title={r.slotTitle} />
        )}
        {(r.marks ?? []).filter((m) => m.at > to).map((m) => (
          <span key={m.key} className="absolute top-1/2 -translate-x-full -translate-y-1/2 whitespace-nowrap rounded border bg-background px-1 text-[10px] text-muted-foreground"
            style={{ left: `${past * 100}%` }} title={m.title}>
            <span className={`mr-1 inline-block h-2 w-2 rotate-45 ${m.cls ?? 'bg-foreground'}`} />{ruDate(m.at)}.{String(new Date(m.at).getFullYear()).slice(2)} →
          </span>
        ))}
        {(r.marks ?? []).filter((m) => m.at <= to).map((m) => (
          <span key={m.key} className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-background shadow ${m.cls ?? 'bg-white'}`}
            style={{ left: pct(m.at) }} title={m.title} />
        ))}
      </>, sub ? 'min-h-9' : 'min-h-[52px]')}
    </div>
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <div className="inline-flex overflow-hidden rounded border" role="group" aria-label="Масштаб шкалы">
          {SCALES.map((s) => <button key={s.k} type="button" aria-pressed={scale === s.k} onClick={() => setScale(s.k)}
            disabled={s.max != null && span > s.max} title={s.max != null && span > s.max ? 'Проект слишком длинный для такого масштаба' : undefined}
            className={`px-2 py-1 disabled:opacity-40 ${scale === s.k ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>{s.label}</button>)}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs" role="group" aria-label="Отбор на диаграмме">
        {FILTERS.filter((f) => f.k !== 'overdue' || hasNorm).map((f) => {
          const n = count(f.k)
          return <button key={f.k} type="button" title={f.hint} aria-pressed={filter === f.k} onClick={() => setFilter(f.k)}
            disabled={f.k !== 'all' && n === 0}
            className={`rounded-full border px-2.5 py-1 disabled:opacity-40 ${filter === f.k ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
            {f.label} <span className="tabular-nums opacity-70">{n}</span>
          </button>
        })}
      </div>
      {parents.length > 0 && (filter === 'all' || filter === 'overdue') && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button type="button" className="rounded border px-2 py-1 hover:bg-muted"
            onClick={() => setOpen(open.size ? new Set() : new Set(parents.map((r) => r.key)))}>{open.size ? 'Свернуть все' : 'Раскрыть все стадии'}</button>
          <div className="inline-flex overflow-hidden rounded border" role="group" aria-label="Какие пункты показывать">
            <button type="button" aria-pressed={!allItems} onClick={() => setAllItems(false)} className={`px-2 py-1 ${!allItems ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>Критичные пункты</button>
            <button type="button" aria-pressed={allItems} onClick={() => setAllItems(true)} className={`px-2 py-1 ${allItems ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>Все пункты</button>
          </div>
          <span className="text-muted-foreground">Стрелка у стадии раскрывает её пункты чек-листа: полоса — от входа в стадию до подтверждения, пунктир — пункт ещё открыт.</span>
        </div>
      )}
      <div ref={box} className="overflow-x-auto rounded-lg border">
        <div style={{ minWidth: 240 + lanePx }}>
          <div className="grid grid-cols-[240px_1fr] border-b bg-muted/40 text-[11px] text-muted-foreground">
            <div className="sticky left-0 z-10 border-r bg-muted px-3 py-2 font-medium">Стадия</div>
            <div className="relative h-9">
              {ticks.filter((k) => Math.abs(x(k.t) - x(now)) > 3).map((k) => (
                <span key={k.t} className={`absolute top-1 -translate-x-1/2 whitespace-nowrap ${k.strong ? 'font-medium text-foreground' : ''}`} style={{ left: pct(k.t) }}>{k.label}</span>
              ))}
              <span className="absolute bottom-0.5 -translate-x-1/2 whitespace-nowrap rounded bg-red-500 px-1.5 text-[10px] font-medium text-white" style={{ left: pct(now) }}>сейчас · {ruDate(now)} {hm(now)}</span>
              {ahead > 0 && <span className="absolute top-1 right-0 text-center uppercase tracking-wide" style={{ left: `${past * 100}%` }}>впереди · сроков нет</span>}
            </div>
          </div>
          {groups.filter((g) => shownRows(g.rows).length > 0).map((g) => {
            const segs = g.rows.filter((r) => r.state !== 'track').flatMap((r) => r.segments)
            const queued = g.rows.map((r) => r.slot).filter((s): s is number => s != null)
            return (
              <div key={g.key}>
                <div className="grid grid-cols-[240px_1fr] border-b bg-muted/20">
                  <div className="sticky left-0 z-10 border-r bg-muted px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{g.label}</div>
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
                {shownRows(g.rows).map((r) => [renderRow(r),
                  ...shownChildren(r).map((c) => renderRow(c, true)),
                  (filter === 'all' || filter === 'overdue') && open.has(r.key) && !allItems && (r.children ?? []).some((c) => !c.required) && (
                    <button key={`${r.key}:more`} type="button" onClick={() => setAllItems(true)}
                      className="block w-full border-b bg-muted/10 py-1 pl-7 text-left text-[11px] text-muted-foreground hover:text-foreground">
                      ещё {(r.children ?? []).filter((c) => !c.required).length} необязательных — показать все пункты
                    </button>
                  ),
                ])}
              </div>
            )
          })}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{legend}</p>
    </div>
  )
}
