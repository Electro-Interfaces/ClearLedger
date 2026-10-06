/**
 * Диаграмма Ганта интеграции — вкладка «Гант» (просьба МАГа 06.10.2026: «классическую
 * диаграмму, чтобы видеть этапы выполнения проекта»).
 *
 * Плановых дат нет (сетку плана убрали — их не знают), поэтому полосы — ФАКТ: стадия
 * длится от входа в неё (журнал переходов маршрута) до входа в следующую, текущая —
 * до сегодня. Ромбы на полосе — подтверждённые пункты чек-листа по дате подтверждения:
 * видно, когда что закрывали и где стояли. Будущие стадии — пустые строки.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getProjectCase, FUNNEL_STAGES, type SiteDetail, type GateState } from '@/services/sitesService'
import { getIntegration } from '@/services/projectIntegrationService'

const PHASES = [
  { key: 'scenario', label: 'Сценарий', stages: ['lead', 'screening'] },
  { key: 'terms', label: 'Условия', stages: ['negotiation', 'dd'] },
  { key: 'pilot', label: 'Пилот', stages: ['decision', 'contracting', 'construction'] },
  { key: 'launch', label: 'Запуск', stages: ['commissioning', 'live'] },
]
const DAY = 86_400_000
const dayStart = (t: number) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime() }
const ru = (t: number, opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit' }) => new Date(t).toLocaleDateString('ru-RU', opts)

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
      // Конец — вход в следующую посещённую стадию; у текущей — сегодня.
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
    const from = dayStart(Math.min(...(times.length ? times : [now]), now) - DAY)
    // Справа запас под будущие стадии: 30 % отрезка, не меньше двух недель.
    const span0 = Math.max(dayStart(now) + DAY - from, 7 * DAY)
    const to = dayStart(now) + DAY + Math.max(span0 * 0.3, 14 * DAY)
    return { rows, from, to, now }
  }, [integ.data, kase.data, site.stage, site.prevStage])

  if (!model) return <p className="text-sm text-muted-foreground">{integ.isError ? `Не загрузилось: ${integ.error.message}` : 'Загрузка…'}</p>
  const { rows, from, to, now } = model
  const span = to - from
  const pct = (t: number) => `${((t - from) / span) * 100}%`
  const days = Math.round(span / DAY)
  // Шаг шкалы: дни до 3 недель, недели до 4 месяцев, дальше месяцы.
  const ticks: { t: number; label: string }[] = []
  if (days <= 21) for (let t = from; t <= to; t += DAY) ticks.push({ t, label: ru(t, { day: 'numeric' }) })
  else if (days <= 120) { let t = from; while (new Date(t).getDay() !== 1) t += DAY; for (; t <= to; t += 7 * DAY) ticks.push({ t, label: ru(t) }) }
  else { const d = new Date(from); d.setDate(1); d.setMonth(d.getMonth() + 1); for (; d.getTime() <= to; d.setMonth(d.getMonth() + 1)) ticks.push({ t: d.getTime(), label: d.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }) }) }
  const byStage = new Map<string, (typeof rows)[number]>(rows.map((r) => [r.stage, r]))

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-lg border">
        <div className="min-w-[760px]">
          {/* Шкала */}
          <div className="grid grid-cols-[230px_1fr] border-b bg-muted/40 text-[11px] text-muted-foreground">
            <div className="px-3 py-1.5 font-medium">Стадия</div>
            <div className="relative h-7">
              {/* Число под меткой «сегодня» не пишем — они накладывались */}
              {ticks.filter((k) => Math.abs(k.t - dayStart(now)) >= DAY / 2 || days > 21).map((k) => <span key={k.t} className="absolute top-1.5 -translate-x-1/2 whitespace-nowrap" style={{ left: pct(k.t) }}>{k.label}</span>)}
              <span className="absolute bottom-0 -translate-x-1/2 rounded-t bg-red-500 px-1 text-[10px] text-white" style={{ left: pct(now) }}>сегодня</span>
            </div>
          </div>
          {PHASES.map((ph) => (
            <div key={ph.key}>
              <div className="grid grid-cols-[230px_1fr] bg-muted/20 border-b">
                <div className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{ph.label}</div>
                <div className="relative min-h-6">
                  <div className="pointer-events-none absolute inset-y-0 w-px bg-red-500/70" style={{ left: pct(now) }} />
                  {/* Сводная полоса этапа — от первого входа до конца последней стадии */}
                  {(() => {
                    const rs = ph.stages.map((s) => byStage.get(s)).filter((r) => r && r.start != null) as NonNullable<ReturnType<typeof byStage.get>>[]
                    if (!rs.length) return null
                    const a = Math.min(...rs.map((r) => r.start!)); const b = Math.max(...rs.map((r) => r.end ?? r.start!))
                    return <div className="absolute top-1/2 h-1 -translate-y-1/2 rounded bg-foreground/30" style={{ left: pct(a), width: `max(3px, calc(${pct(b)} - ${pct(a)}))` }} />
                  })()}
                </div>
              </div>
              {ph.stages.map((st) => {
                const r = byStage.get(st); if (!r) return null
                const color = r.state === 'done' ? 'bg-emerald-500/80' : r.state === 'current' ? 'bg-primary' : r.state === 'stopped' ? 'bg-amber-500' : ''
                const dur = r.start != null && r.end != null ? Math.max(1, Math.round((r.end - r.start) / DAY)) : null
                return (
                  <div key={st} className="grid grid-cols-[230px_1fr] border-b last:border-b-0 hover:bg-muted/30">
                    <button type="button" disabled={!onStage} onClick={() => onStage?.(`int_${st}`)}
                      className="px-3 py-2 text-left text-sm disabled:cursor-default" title={onStage ? 'Открыть работу стадии' : undefined}>
                      <div className={r.state === 'future' ? 'text-muted-foreground' : r.state === 'current' ? 'font-medium' : ''}>{r.label}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {r.state === 'future' ? 'не начата' : `${r.start ? ru(r.start) : '?'} — ${r.state === 'current' ? 'сейчас' : r.end ? ru(r.end) : '?'}${dur ? ` · ${dur} дн.` : ''}`}
                        {r.reqTotal > 0 && ` · ${r.reqDone}/${r.reqTotal}`}
                      </div>
                    </button>
                    <div className="relative">
                      <div className="pointer-events-none absolute inset-y-0 w-px bg-red-500/70" style={{ left: pct(now) }} />
                      {r.start != null && r.end != null && (
                        <div className={`absolute top-1/2 h-4 -translate-y-1/2 rounded ${color} ${r.state === 'current' ? 'bg-[linear-gradient(90deg,transparent_0,transparent_6px,rgba(255,255,255,.25)_6px,rgba(255,255,255,.25)_12px)] bg-[length:12px_100%]' : ''}`}
                          style={{ left: pct(r.start), width: `max(4px, calc(${pct(r.end)} - ${pct(r.start)}))` }}
                          title={`${r.label}: ${ru(r.start)} — ${r.state === 'current' ? 'сейчас' : ru(r.end)}`} />
                      )}
                      {r.marks.map((m) => (
                        <span key={m.key} className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-background bg-foreground"
                          style={{ left: pct(m.at) }} title={`${m.key} ${m.label}\nподтверждён ${new Date(m.at).toLocaleString('ru-RU')}${m.by ? ` · ${m.by}` : ''}`} />
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Полосы — фактическое время на стадии: от входа в неё до входа в следующую (у текущей — до сегодня; штриховка). ◆ — подтверждённый пункт чек-листа, наведите для подробностей.
        Будущие стадии без дат: плановых сроков в проекте нет. Нажатие на название стадии открывает её работу.
      </p>
    </div>
  )
}
