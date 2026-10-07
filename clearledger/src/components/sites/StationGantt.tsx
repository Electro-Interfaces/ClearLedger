/**
 * Диаграмма Ганта проекта станции — вкладка «Гант» (просьба МАГа 07.10.2026).
 * Отрисовка общая с интеграцией — `GanttChart`.
 *
 * Стадии и этапы — из «Пути проекта» (та же выборка, что у «Схемы»), отрезки — из
 * истории смен стадии: вход в стадию открывает отрезок, следующая смена закрывает.
 * Возврат на доработку даёт второй отрезок той же строки.
 *
 * История смен стадии ведётся с 31.07.2026; проекты, импортированные 23.07, её не
 * имеют. Такие стадии не рисуются выдуманной полосой: пройденная — «дата не
 * записана», текущая — от даты начала учёта с пометкой. Даты параллельных треков
 * (ТП, договор, ввод) и поступления заявки — ромбы: это реальные даты.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getProjectRoadmap, getSiteEvents, type SiteDetail } from '@/services/sitesService'
import { GanttChart, type GanttGroup, type GanttRow, type GanttState } from './GanttChart'
import { ruDate, dur, DAY } from './ganttTime'
import { itemRows } from './ganttItems'

const TRACK_MARK: Record<string, string> = {
  done: 'bg-emerald-500', current: 'bg-primary', overdue: 'bg-red-500', failed: 'bg-red-500', waiting: 'bg-muted-foreground',
}
const parse = (s: string | null | undefined) => {
  if (!s) return null
  const t = new Date(s.length === 10 ? `${s}T00:00:00` : s).getTime()
  return Number.isNaN(t) ? null : t
}

export function StationGantt({ site, companyId, onStage }: { site: SiteDetail; companyId: string; onStage?: (code: string) => void }) {
  const road = useQuery({ queryKey: ['site-roadmap', companyId, site.id], queryFn: () => getProjectRoadmap(companyId, site.id) })
  const ev = useQuery({ queryKey: ['site-events', companyId, site.id, 'stage'], queryFn: () => getSiteEvents(companyId, site.id, 'stage') })
  const [now] = useState(() => Date.now())
  if (!road.data || ev.isLoading) return <p className="text-sm text-muted-foreground">{road.isError ? `Не загрузилось: ${road.error.message}` : 'Загрузка…'}</p>

  const d = road.data
  // Отрезки по стадиям из истории смен: событие открывает отрезок «куда», закрывает прежний.
  const segs = new Map<string, { start: number; end: number }[]>()
  const changes = (ev.data ?? []).filter((e) => e.toStage && e.createdAt)
    .map((e) => ({ from: e.fromStage, to: e.toStage!, at: new Date(e.createdAt!).getTime() })).sort((a, b) => a.at - b.at)
  let open: { stage: string; start: number } | null = null
  for (const c of changes) {
    if (open) segs.set(open.stage, [...(segs.get(open.stage) ?? []), { start: open.start, end: c.at }])
    open = { stage: c.to, start: c.at }
  }
  const tracked = changes.length > 0
  const since = parse(site.stageSince)
  const cur = d.steps.find((s) => s.state === 'current' || s.state === 'stopped')
  if (open && open.stage === site.stage) segs.set(open.stage, [...(segs.get(open.stage) ?? []), { start: open.start, end: now }])
  // Текущая без истории — от начала учёта стадии (у импорта это дата импорта).
  const untracked = cur?.state === 'current' && !segs.has(cur.key) && since != null
  if (untracked) segs.set(cur!.key, [{ start: since!, end: now }])

  const waiting = d.steps.filter((s) => s.state === 'waiting' || s.state === 'unknown').map((s) => s.key as string)
  const queue = site.stage === 'archive' || !waiting.length ? [] : cur?.state === 'current' ? [cur.key as string, ...waiting] : waiting
  const received = parse(site.receivedDate)

  const groups: GanttGroup[] = d.phases.map((ph) => {
    const stages: GanttRow[] = d.steps.filter((s) => s.phase === ph.key).map((s, i) => {
      const state: GanttState = s.state === 'done' ? 'done' : s.state === 'current' ? 'current' : s.state === 'stopped' ? 'stopped' : 'future'
      const list = segs.get(s.key) ?? []
      const total = list.reduce((a, x) => a + (x.end - x.start), 0)
      const first = list[0]?.start, last = list[list.length - 1]?.end
      const slot = queue.indexOf(s.key)
      const when = state === 'future' ? 'впереди'
        : !list.length ? (state === 'done' ? 'пройдена · дата не записана' : 'дата входа не записана')
        : `${ruDate(first!)} — ${state === 'current' ? 'сейчас' : ruDate(last!)} · ${dur(total)}${list.length > 1 ? ` · ${list.length} захода` : ''}${state === 'current' && untracked ? ' · с начала учёта' : ''}`
      return {
        key: s.key, label: s.label, state, segments: list,
        sub: `${when}${s.gateTotal ? ` · чек-лист ${s.gateDone}/${s.gateTotal}` : ''}`,
        marks: i === 0 && ph.key === d.steps[0]?.phase && received != null
          ? [{ key: 'received', at: received, title: `Заявка поступила ${ruDate(received)}`, cls: 'bg-sky-400' }] : [],
        slot: slot >= 0 ? slot : undefined,
        slotTitle: `${s.label}: ${state === 'future' ? 'впереди' : 'текущая'}, чек-лист ${s.gateDone}/${s.gateTotal}`,
        onOpen: onStage && (() => onStage(s.key)),
        normMs: s.normDays ? s.normDays * DAY : undefined,
        children: itemRows(s.key, s.items, state, list[0]?.start ?? null, now, (r) => r, onStage && (() => onStage(s.key))),
      }
    })
    const tracks: GanttRow[] = d.tracks.filter((t) => t.phase === ph.key && t.state !== 'empty').map((t) => {
      const at = parse(t.date)
      return {
        key: `track:${t.key}`, label: `∥ ${t.label}`, state: 'track' as const, segments: [],
        sub: `${t.status}${t.date ? ` · ${at != null ? ruDate(at) : t.date}` : ''}`,
        marks: at != null ? [{ key: t.key, at, title: `${t.label}: ${t.status} · ${ruDate(at)}${t.detail ? `\n${t.detail}` : ''}`, cls: TRACK_MARK[t.state] ?? 'bg-muted-foreground' }] : [],
      }
    })
    return { key: ph.key, label: ph.label, rows: [...stages, ...tracks] }
  }).filter((g) => g.rows.length > 0)

  return <GanttChart now={now} groups={groups} legend={<>
    Слева — факт по истории смен стадии (зелёная — пройдена, синяя — текущая, жёлтая — остановлена); у проектов, заведённых до 31.07.2026, история смен не велась — там «дата не записана», а текущая стадия считается с начала учёта.
    ∥ — параллельные треки этапа (право, ТП, оборудование, договор, ввод): ромб — их дата (зелёный — выполнено, красный — просрочено), голубой ромб — поступление заявки.
    Справа — что впереди, по порядку стадий; ширина условная. Нажатие на строку стадии открывает «Работу».{!tracked && !untracked && ' Истории смен стадии у проекта нет.'}
  </>} />
}
