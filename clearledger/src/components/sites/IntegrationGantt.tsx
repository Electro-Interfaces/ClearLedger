/**
 * Диаграмма Ганта интеграции — вкладка «Гант» (просьба МАГа 06.10.2026: «классическую
 * диаграмму, чтобы видеть этапы выполнения проекта»).
 *
 * Плановых дат нет (сетку плана убрали — их не знают), поэтому шкала делится на две
 * зоны. Слева — ФАКТ: стадия длится от входа в неё (журнал переходов маршрута) до входа
 * в следующую, текущая — до сейчас; шкала растянута ровно на прожитое время (у молодого
 * проекта — по часам), без пустых недель. Справа — «впереди»: оставшиеся стадии лесенкой
 * в порядке маршрута, равными долями и без дат — очередь, а не прогноз.
 * Ромбы — подтверждённые пункты чек-листа по дате подтверждения.
 */
import { useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getProjectCase, FUNNEL_STAGES, type SiteDetail, type GateState } from '@/services/sitesService'
import { getIntegration } from '@/services/projectIntegrationService'

const PHASES = [
  { key: 'scenario', label: 'Сценарий', stages: ['lead', 'screening'] },
  { key: 'terms', label: 'Условия', stages: ['negotiation', 'dd'] },
  { key: 'pilot', label: 'Пилот', stages: ['decision', 'contracting', 'construction'] },
  { key: 'launch', label: 'Запуск', stages: ['commissioning', 'live'] },
]
const H = 3_600_000
const DAY = 24 * H
/** Шаги шкалы: берём первый, при котором делений в зоне факта не больше 12. */
const STEPS = [H, 2 * H, 3 * H, 6 * H, 12 * H, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY]
const dayStart = (t: number) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime() }
const ru = (t: number) => new Date(t).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
const hm = (t: number) => new Date(t).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
const dur = (ms: number) => ms < H ? '<1 ч' : ms < DAY ? `${Math.round(ms / H)} ч` : `${Math.round(ms / DAY)} дн.`
/** Доля ширины под «впереди», если есть будущие стадии. */
const AHEAD = 0.32

export function IntegrationGantt({ site, companyId, onStage }: { site: SiteDetail; companyId: string; onStage?: (code: string) => void }) {
  const integ = useQuery({ queryKey: ['project-integration', companyId, site.id], queryFn: () => getIntegration(companyId, site.id) })
  const kase = useQuery({ queryKey: ['site-case', companyId, site.id], queryFn: () => getProjectCase(companyId, site.id) })

  const model = useMemo(() => {
    if (!integ.data) return null
    const gates = new Map<string, GateState>(integ.data.gates.map((g) => [g.stage, g]))
    const entered = new Map<string, number>()
    for (const s of kase.data?.stages ?? []) {
      if (s.code.startsWith('int_') && s.visited_at) entered.set(s.code.slice(4), new Date(s.visited_at).getTime())
    }
    const now = Date.now()
    const stopped = site.stage === 'on_hold' || site.stage === 'archive'
    const anchor = stopped ? (site.prevStage ?? '') : site.stage
    const curIdx = FUNNEL_STAGES.indexOf(anchor as never)
    const rows = FUNNEL_STAGES.filter((st) => gates.has(st)).map((st, i, all) => {
      const idx = FUNNEL_STAGES.indexOf(st)
      const start = entered.get(st) ?? null
      const nextStart = all.slice(i + 1).map((n) => entered.get(n)).find((t) => t != null) ?? null
      const state = idx < curIdx ? 'done' : idx === curIdx ? (stopped ? 'stopped' : 'current') : 'future'
      const end = state === 'current' || state === 'stopped' ? now : nextStart
      const g = gates.get(st)!
      const marks = g.items.filter((it) => it.done && it.confirmedAt)
        .map((it) => ({ key: it.key, label: it.label, at: new Date(it.confirmedAt!).getTime(), by: it.confirmedBy ?? '' }))
      const req = g.items.filter((it) => it.required)
      return { stage: st, label: g.stageLabel, state, start, end, marks, reqDone: req.filter((it) => it.done || it.waived).length, reqTotal: req.length }
    })
    const times = rows.flatMap((r) => [r.start, r.end, ...r.marks.map((m) => m.at)]).filter((t): t is number => t != null)
    const t0 = Math.min(...(times.length ? times : [now - DAY]))
    const pad = Math.max((now - t0) * 0.04, 0.5 * H)
    const from = t0 - pad
    const to = now + pad
    // Очередь впереди: текущая стадия продолжается пунктиром в первой доле, дальше — будущие.
    const future = rows.filter((r) => r.state === 'future').map((r) => r.stage)
    const slots = stopped ? future : [anchor, ...future]
    return { rows, from, to, now, slots }
  }, [integ.data, kase.data, site.stage, site.prevStage])

  if (!model) return <p className="text-sm text-muted-foreground">{integ.isError ? `Не загрузилось: ${integ.error.message}` : 'Загрузка…'}</p>
  const { rows, from, to, now, slots } = model
  const ahead = slots.length > 1 || (slots.length === 1 && rows.some((r) => r.state === 'future')) ? AHEAD : 0
  const past = 1 - ahead
  const span = to - from
  const x = (t: number) => ((t - from) / span) * past * 100
  const pct = (t: number) => `${x(t)}%`
  const slotW = slots.length ? (ahead * 100) / slots.length : 0
  const slotOf = (st: string) => slots.indexOf(st)

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
      ticks.push({ t, label: step < DAY ? (midnight ? ru(t) : hm(t)) : ru(t), strong: midnight })
    }
  }
  const byStage = new Map<string, (typeof rows)[number]>(rows.map((r) => [r.stage, r]))

  // Фон дорожки: сетка делений и зона «впереди» — одинаковые у всех строк.
  const Lane = ({ children, h = 'min-h-[52px]' }: { children?: ReactNode; h?: string }) => (
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
          {/* Шкала */}
          <div className="grid grid-cols-[240px_1fr] border-b bg-muted/40 text-[11px] text-muted-foreground">
            <div className="px-3 py-2 font-medium">Стадия</div>
            <div className="relative h-9">
              {ticks.filter((k) => Math.abs(x(k.t) - x(now)) > 3).map((k) => (
                <span key={k.t} className={`absolute top-1 -translate-x-1/2 whitespace-nowrap ${k.strong ? 'font-medium text-foreground' : ''}`} style={{ left: pct(k.t) }}>{k.label}</span>
              ))}
              <span className="absolute bottom-0.5 -translate-x-1/2 whitespace-nowrap rounded bg-red-500 px-1.5 text-[10px] font-medium text-white" style={{ left: pct(now) }}>сейчас · {ru(now)} {hm(now)}</span>
              {ahead > 0 && (
                <span className="absolute top-1 right-0 text-center uppercase tracking-wide" style={{ left: `${past * 100}%` }}>впереди · сроков нет</span>
              )}
            </div>
          </div>
          {PHASES.map((ph) => {
            const rs = ph.stages.map((s) => byStage.get(s)).filter(Boolean) as NonNullable<ReturnType<typeof byStage.get>>[]
            const started = rs.filter((r) => r.start != null)
            const queued = rs.map((r) => slotOf(r.stage)).filter((i) => i >= 0)
            return (
              <div key={ph.key}>
                <div className="grid grid-cols-[240px_1fr] border-b bg-muted/20">
                  <div className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{ph.label}</div>
                  <Lane h="min-h-7">
                    {/* Сводная полоса этапа: факт — сплошная, очередь — пунктир */}
                    {started.length > 0 && (() => {
                      const a = Math.min(...started.map((r) => r.start!)); const b = Math.max(...started.map((r) => r.end ?? r.start!))
                      return <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded bg-foreground/40" style={{ left: pct(a), width: `max(3px, calc(${pct(b)} - ${pct(a)}))` }} />
                    })()}
                    {queued.length > 0 && (
                      <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded border border-dashed border-foreground/30"
                        style={{ left: `${past * 100 + Math.min(...queued) * slotW}%`, width: `${(Math.max(...queued) - Math.min(...queued) + 1) * slotW}%` }} />
                    )}
                  </Lane>
                </div>
                {rs.map((r) => {
                  const color = r.state === 'done' ? 'bg-emerald-500' : r.state === 'current' ? 'bg-primary' : 'bg-amber-500'
                  const len = r.start != null && r.end != null ? r.end - r.start : null
                  const slot = slotOf(r.stage)
                  return (
                    // Вся строка — и название, и полоса — открывает работу стадии (МАГ 06.10.2026).
                    <div key={r.stage} onClick={() => onStage?.(`int_${r.stage}`)} title={onStage ? 'Открыть работу стадии' : undefined}
                      className={`grid grid-cols-[240px_1fr] border-b last:border-b-0 hover:bg-muted/40 ${onStage ? 'cursor-pointer' : ''}`}>
                      <button type="button" disabled={!onStage} className="px-3 py-2 text-left text-sm disabled:cursor-default">
                        <div className={r.state === 'future' ? 'text-muted-foreground' : r.state === 'current' ? 'font-semibold' : ''}>{r.label}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {r.state === 'future' ? 'впереди' : `${r.start ? ru(r.start) : '?'} — ${r.state === 'current' ? 'сейчас' : r.end ? ru(r.end) : '?'}${len != null ? ` · ${dur(len)}` : ''}`}
                          {r.reqTotal > 0 && ` · пункты ${r.reqDone}/${r.reqTotal}`}
                        </div>
                      </button>
                      <Lane>
                        {r.start != null && r.end != null && (
                          <div className={`absolute top-1/2 flex h-6 -translate-y-1/2 items-center overflow-hidden rounded px-1.5 text-[11px] font-medium text-white ${color}`}
                            style={{ left: pct(r.start), width: `max(6px, calc(${pct(r.end)} - ${pct(r.start)}))` }}
                            title={`${r.label}: ${ru(r.start)} ${hm(r.start)} — ${r.state === 'current' ? 'сейчас' : `${ru(r.end)} ${hm(r.end)}`}`}>
                            {len != null && x(r.end) - x(r.start) > 5 && <span className="truncate">{dur(len)}</span>}
                          </div>
                        )}
                        {slot >= 0 && (
                          <div className={`absolute top-1/2 h-6 -translate-y-1/2 rounded border border-dashed ${r.state === 'future' ? 'border-muted-foreground/40' : 'border-primary/60 bg-primary/10'}`}
                            style={{ left: `calc(${past * 100 + slot * slotW}% + 2px)`, width: `calc(${slotW}% - 4px)` }}
                            title={r.state === 'future' ? `${r.label}: впереди, пунктов ${r.reqTotal}` : `${r.label}: осталось ${r.reqTotal - r.reqDone} из ${r.reqTotal}`} />
                        )}
                        {r.marks.map((m) => (
                          <span key={m.key} className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-background bg-white shadow"
                            style={{ left: pct(m.at) }} title={`${m.key} ${m.label}\nподтверждён ${new Date(m.at).toLocaleString('ru-RU')}${m.by ? ` · ${m.by}` : ''}`} />
                        ))}
                      </Lane>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Слева — факт: сколько проект простоял на каждой стадии (зелёная — пройдена, синяя — текущая), ◆ — подтверждённый пункт, наведите для подробностей.
        Справа — что впереди, по порядку маршрута; ширина условная: плановых сроков в проекте нет. Нажатие на строку стадии открывает её работу.
      </p>
    </div>
  )
}
