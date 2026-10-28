import { formatDate } from '../../lib/formatDate.ts'
import type { TechConnectionView, TpViewStep, TpViewBranch } from '@/services/techConnectionView'
import type { GanttGroup, GanttRow, GanttMark } from './GanttChart'
import { ruDate } from './ganttTime.ts'
const time = (value?: string | null) => { const n = value ? Date.parse(value) : NaN; return Number.isFinite(n) ? n : null }
const stepPhase: Record<string, string> = { indirect_agreement: 'collect', docs_ready: 'collect', applied: 'submit', documents_review: 'grid', accepted: 'grid', contract: 'grid', works_done: 'works', notified: 'works', checked: 'inspect', avtu: 'documents', atp: 'documents', supply_applied: 'supply_prepare', supply_contract: 'supply_wait' }
const stamp = (key: string, value: string | null, label: string, planned = false, late = false): GanttMark[] => {
  const at = time(value)
  return at == null ? [] : [{ key, at, title: `${planned ? 'План' : 'Факт'}: ${label} · ${ruDate(at)}`, cls: late ? 'bg-red-500' : planned ? 'bg-amber-500' : 'bg-emerald-500' }]
}
function factRow(step: TpViewStep, open: () => void): GanttRow {
  return { key: `tp:step:${step.key}`, label: `${step.no} ${step.label}`, source: 'tp', deadlineOverdue: step.overdue,
    state: step.date ? 'done' : 'future', segments: [], onOpen: open,
    sub: [step.date ? `факт ${formatDate(step.date)}` : 'факт не отмечен', step.plannedDate ? `план ${formatDate(step.plannedDate)}` : 'срок не назначен', step.executor].filter(Boolean).join(' · '),
    marks: [...stamp('fact', step.date, step.label), ...stamp('plan', step.plannedDate, step.label, true, step.overdue)] }
}
function processRows(branch: TpViewBranch, facts: TpViewStep[], now: number, open: () => void): GanttRow[] {
  const intervals = new Map<string, { start: number; end: number }[]>()
  const events = branch.history.map((e) => ({ ...e, atMs: time(e.at) })).filter((e) => e.atMs != null).sort((a, b) => a.atMs! - b.atMs!)
  let current = branch.steps.find((s) => s.is_initial)?.code ?? null
  let start = time(branch.startedAt)
  for (const event of events) {
    if (current && start != null && event.atMs! >= start) intervals.set(current, [...(intervals.get(current) ?? []), { start, end: event.atMs! }])
    current = event.to_code; start = event.atMs
  }
  if (branch.state === 'running' && branch.stage.code && current === branch.stage.code && start != null && start <= now) {
    intervals.set(current, [...(intervals.get(current) ?? []), { start, end: now }])
  }
  return branch.steps.filter((s) => s.code !== 'correction' || s.code === branch.stage.code || intervals.has(s.code)).map((step) => {
    const linked = facts.filter((f) => stepPhase[f.key] === step.code)
    const segments = intervals.get(step.code) ?? []
    const isCurrent = step.code === branch.stage.code && branch.state !== 'done'
    const visited = segments.length > 0 || !!step.visited_at || (step.code === branch.stage.code && branch.state === 'done')
    return { key: `tp:process:${branch.key}:${step.code}`, label: step.name, source: 'tp', onOpen: open,
      state: isCurrent ? 'current' : visited ? 'done' : 'future', segments,
      deadlineOverdue: linked.some((f) => f.overdue),
      sub: [isCurrent ? branch.performer?.name || 'текущий шаг процесса' : visited ? 'есть подтверждённая история' : 'не выполнялся',
        ...linked.map((f) => `${f.no}: ${f.date ? 'факт ' + formatDate(f.date) : 'факт не отмечен'}${f.plannedDate ? ', план ' + formatDate(f.plannedDate) : ''}`)].join(' · '),
      marks: linked.flatMap((f) => [...stamp('fact:' + f.key, f.date, f.label), ...stamp('plan:' + f.key, f.plannedDate, f.label, true, f.overdue)]) }
  })
}
export function tpGanttRows(view: TechConnectionView | null | undefined, now: number, open: () => void): GanttGroup[] {
  if (!view) return []
  const groups: GanttGroup[] = []
  for (const branch of view.branches) {
    const facts = view.steps.filter((s) => s.branch === (branch.key === 'tp_supply' ? 'supply' : 'main'))
    const rows = branch.steps.length ? processRows(branch, facts, now, open) : facts.map((s) => factRow(s, open))
    if (rows.length) groups.push({ key: 'tp:' + branch.key, label: `${branch.label}${view.enabled ? '' : ' · по датам карточки'}`, rows })
  }
  if (view.stages?.length) groups.push({ key: 'tp:works', label: 'Этапы выполнения ТУ', rows: view.stages.map((stage) => {
    const late = !!stage.due && !stage.done && stage.due < new Date(now).toISOString().slice(0, 10)
    const done = time(stage.done), end = time(stage.accepted)
    return { key: 'tp:stage:' + stage.id, label: stage.title, source: 'tp', deadlineOverdue: late, onOpen: open,
      state: stage.accepted ? 'done' : stage.done ? 'current' : 'future',
      segments: done != null && end != null && end >= done ? [{ start: done, end }] : [],
      sub: [stage.executor, stage.due && `план ${formatDate(stage.due)}`, stage.done && `выполнено ${formatDate(stage.done)}`, stage.notified && `уведомлено ${formatDate(stage.notified)}`, stage.accepted && `принято ${formatDate(stage.accepted)}`].filter(Boolean).join(' · '),
      marks: [...stamp('plan', stage.due, stage.title, true, late), ...stamp('done', stage.done, 'Работы выполнены'), ...stamp('notice', stage.notified, 'Сетевая уведомлена'), ...stamp('accepted', stage.accepted, 'Этап принят')] }
  }) })
  if (view.remarks?.length) groups.push({ key: 'tp:remarks', label: 'Замечания по ТП и сбыту', rows: view.remarks.map((r) => {
    const start = time(r.received), end = time(r.resolved)
    return { key: 'tp:remark:' + r.id, label: r.text, source: 'tp', deadlineOverdue: r.overdue, onOpen: open,
      state: r.resolved ? 'done' : 'current', segments: start == null ? [] : [{ start, end: end ?? now }],
      sub: `${r.branch === 'supply' ? 'Сбыт' : 'Сетевая'} · получено ${formatDate(r.received)} · срок ${formatDate(r.deadline)}${r.resolved ? ' · снято ' + formatDate(r.resolved) : ' · открыто'}`,
      marks: stamp('plan', r.deadline, 'Ответ на замечание', true, r.overdue) }
  }) })
  if (view.handover?.exists) {
    const h = view.handover, start = time(h.createdAt)
    const reads = h.recipients.map((r) => time(r.readAt)).filter((n): n is number => n != null)
    const end = h.done ? (reads.length ? Math.max(...reads) : null) : now
    groups.push({ key: 'tp:handover', label: 'Передача итогового комплекта', rows: [{ key: 'tp:handover:read', label: 'Ознакомление контролирующих', source: 'tp', onOpen: open,
      state: h.done ? 'done' : 'current', segments: start != null && end != null && end >= start ? [{ start, end }] : [],
      sub: h.recipients.map((r) => `${r.name}: ${r.status === 'done' ? 'ознакомлен' : 'ожидается'}`).join(' · ') }] })
  }
  return groups
}
