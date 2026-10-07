/**
 * Диаграмма Ганта интеграции — вкладка «Гант» (просьба МАГа 06.10.2026: «классическую
 * диаграмму, чтобы видеть этапы выполнения проекта»). Отрисовка — `GanttChart`.
 *
 * Полосы — факт по журналу переходов маршрута: стадия длится от входа в неё до входа в
 * следующую, текущая — до сейчас. Ромбы — подтверждённые пункты чек-листа по дате
 * подтверждения. Будущие стадии — очередь «впереди» без дат.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getProjectCase, FUNNEL_STAGES, type SiteDetail, type GateState } from '@/services/sitesService'
import { getIntegration } from '@/services/projectIntegrationService'
import { GanttChart, type GanttGroup } from './GanttChart'
import { ruDate, dur } from './ganttTime'

const PHASES = [
  { key: 'scenario', label: 'Сценарий', stages: ['lead', 'screening'] },
  { key: 'terms', label: 'Условия', stages: ['negotiation', 'dd'] },
  { key: 'pilot', label: 'Пилот', stages: ['decision', 'contracting', 'construction'] },
  { key: 'launch', label: 'Запуск', stages: ['commissioning', 'live'] },
]

export function IntegrationGantt({ site, companyId, onStage }: { site: SiteDetail; companyId: string; onStage?: (code: string) => void }) {
  const integ = useQuery({ queryKey: ['project-integration', companyId, site.id], queryFn: () => getIntegration(companyId, site.id) })
  const kase = useQuery({ queryKey: ['site-case', companyId, site.id], queryFn: () => getProjectCase(companyId, site.id) })
  const [now] = useState(() => Date.now())
  if (!integ.data) return <p className="text-sm text-muted-foreground">{integ.isError ? `Не загрузилось: ${integ.error.message}` : 'Загрузка…'}</p>

  const gates = new Map<string, GateState>(integ.data.gates.map((g) => [g.stage, g]))
  const entered = new Map<string, number>()
  for (const s of kase.data?.stages ?? []) {
    if (s.code.startsWith('int_') && s.visited_at) entered.set(s.code.slice(4), new Date(s.visited_at).getTime())
  }
  const stopped = site.stage === 'on_hold' || site.stage === 'archive'
  const anchor: string = stopped ? (site.prevStage ?? '') : site.stage
  const curIdx = FUNNEL_STAGES.indexOf(anchor as never)
  const order: string[] = FUNNEL_STAGES.filter((st) => gates.has(st))
  const future = order.filter((st) => FUNNEL_STAGES.indexOf(st as never) > curIdx)
  // Очередь: текущая продолжается пунктиром в первой доле, дальше — будущие.
  const queue = future.length ? (stopped ? future : [anchor, ...future]) : []

  const groups: GanttGroup[] = PHASES.map((ph) => ({
    key: ph.key, label: ph.label,
    rows: ph.stages.filter((st) => gates.has(st)).map((st) => {
      const idx = FUNNEL_STAGES.indexOf(st as never)
      const state = idx < curIdx ? 'done' as const : idx === curIdx ? (stopped ? 'stopped' as const : 'current' as const) : 'future' as const
      const start = entered.get(st) ?? null
      const nextStart = order.slice(order.indexOf(st) + 1).map((n) => entered.get(n)).find((t) => t != null) ?? null
      const end = state === 'current' || state === 'stopped' ? now : nextStart
      const g = gates.get(st)!
      const req = g.items.filter((it) => it.required)
      const reqDone = req.filter((it) => it.done || it.waived).length
      const slot = queue.indexOf(st)
      return {
        key: st, label: g.stageLabel, state,
        sub: (state === 'future' ? 'впереди' : `${start ? ruDate(start) : '?'} — ${state === 'current' ? 'сейчас' : end ? ruDate(end) : '?'}${start != null && end != null ? ` · ${dur(end - start)}` : ''}`)
          + (req.length ? ` · пункты ${reqDone}/${req.length}` : ''),
        segments: start != null && end != null ? [{ start, end }] : [],
        marks: g.items.filter((it) => it.done && it.confirmedAt).map((it) => ({
          key: it.key, at: new Date(it.confirmedAt!).getTime(),
          title: `${it.key} ${it.label}\nподтверждён ${new Date(it.confirmedAt!).toLocaleString('ru-RU')}${it.confirmedBy ? ` · ${it.confirmedBy}` : ''}`,
        })),
        slot: slot >= 0 ? slot : undefined,
        slotTitle: state === 'future' ? `${g.stageLabel}: впереди, пунктов ${req.length}` : `${g.stageLabel}: осталось ${req.length - reqDone} из ${req.length}`,
        onOpen: onStage && (() => onStage(`int_${st}`)),
      }
    }),
  }))

  return <GanttChart now={now} groups={groups} legend={<>
    Слева — факт: сколько проект простоял на каждой стадии (зелёная — пройдена, синяя — текущая), ◆ — подтверждённый пункт, наведите для подробностей.
    Справа — что впереди, по порядку маршрута; ширина условная: плановых сроков в проекте нет. Нажатие на строку стадии открывает её работу.
  </>} />
}
