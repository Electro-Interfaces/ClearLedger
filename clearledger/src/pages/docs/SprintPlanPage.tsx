/**
 * Планирование спринта (этап 11 трекерного контура).
 *
 * Доска по стадиям отвечает «где работа стоит», но не отвечает «что берём
 * следующим». Здесь две колонки: слева бэклог проекта, справа спринт; задача
 * переносится перетаскиванием — как на доске поручений, тем же нативным DnD.
 *
 * Бэклог — это отсутствие спринта, а не отдельный список. Отдельная сущность
 * означала бы, что задачу надо положить куда-то дважды.
 *
 * Закрытие спринта — не смена слова: незакрытые задачи возвращаются в бэклог, а
 * их число остаётся в спринте. Иначе итог показал бы «взято столько же, сколько
 * сделано», и по такому отчёту не видно, что отрезок переоценили.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Flag, Loader2, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import { taskKey, type SpaceTask, type TaskSprint } from '@/services/tasksService'
import { cn } from '@/lib/utils'

const STATE_LABEL: Record<TaskSprint['state'], string> = {
  planned: 'план', active: 'идёт', closed: 'закрыт',
}

export function SprintPlanPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [projectId, setProjectId] = useState('')
  const [sprintId, setSprintId] = useState('')
  const [adding, setAdding] = useState(false)
  const [dragged, setDragged] = useState<string | null>(null)
  const [over, setOver] = useState<'backlog' | 'sprint' | null>(null)

  const projectsQ = useQuery({
    queryKey: ['task-projects', company.id, false],
    queryFn: () => tasksService.listTaskProjects(company.id),
  })
  const projects = projectsQ.data?.projects ?? []
  const project = projectId || projects[0]?.id || ''

  const sprintsQ = useQuery({
    queryKey: ['task-sprints', company.id, project],
    queryFn: () => tasksService.listTaskSprints(company.id, project),
    enabled: !!project,
  })
  const sprints = sprintsQ.data?.sprints ?? []
  // По умолчанию открываем тот отрезок, который идёт: планируют обычно его, а
  // не первый по алфавиту.
  const sprint = sprints.find((s) => s.id === sprintId)
    ?? sprints.find((s) => s.state === 'active')
    ?? sprints.find((s) => s.state === 'planned')

  const backlogQ = useQuery({
    queryKey: ['tasks-backlog', company.id, project],
    queryFn: () => tasksService.listTasks(company.id, 'open',
      { projectId: project, backlog: true, limit: 200, sort: '-priority' }),
    enabled: !!project,
  })
  const sprintQ = useQuery({
    queryKey: ['tasks-sprint', company.id, sprint?.id],
    queryFn: () => tasksService.listTasks(company.id, 'all',
      { sprintId: sprint?.id, limit: 200 }),
    enabled: !!sprint,
  })

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['tasks-backlog'] })
    void qc.invalidateQueries({ queryKey: ['tasks-sprint'] })
    void qc.invalidateQueries({ queryKey: ['task-sprints'] })
  }

  const move = useMutation({
    mutationFn: (v: { taskId: string; to: string | null }) =>
      tasksService.taskAction(v.taskId, { companyId: company.id, sprintId: v.to }),
    onSuccess: refresh,
    onError: (e) => toast.error((e as Error).message),
  })
  const setState = useMutation({
    mutationFn: (state: TaskSprint['state']) =>
      tasksService.updateTaskSprint(sprint!.id, { companyId: company.id, state }),
    onSuccess: (r) => {
      refresh()
      toast.success(r.state === 'closed'
        ? `Спринт закрыт: сделано ${r.done}, перенесено ${r.carried_over}`
        : 'Спринт идёт')
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const drop = (to: 'backlog' | 'sprint') => {
    setOver(null)
    const taskId = dragged
    setDragged(null)
    if (!taskId) return
    if (to === 'sprint' && !sprint) {
      toast.error('Сначала заведите спринт')
      return
    }
    move.mutate({ taskId, to: to === 'sprint' ? sprint!.id : null })
  }

  if (projectsQ.isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Загрузка…
      </div>
    )
  }
  if (projects.length === 0) {
    return (
      <div className="space-y-3 p-4">
        <h1 className="text-lg font-semibold">Планирование</h1>
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Спринты живут на проекте, а проектов пока нет. Заведите первый в
          настройке «Трека», раздел «Проекты».
        </div>
      </div>
    )
  }

  const backlog = backlogQ.data?.tasks ?? []
  const inSprint = sprintQ.data?.tasks ?? []
  const closed = sprint?.state === 'closed'

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-lg font-semibold">Планирование</h1>
        <Select value={project} onValueChange={(v) => { setProjectId(v); setSprintId('') }}>
          <SelectTrigger className="h-8 w-[200px] text-xs">
            <SelectValue placeholder="Проект" />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.code} · {p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {sprints.length > 0 && (
          <Select value={sprint?.id ?? ''} onValueChange={setSprintId}>
            <SelectTrigger className="h-8 w-[220px] text-xs">
              <SelectValue placeholder="Спринт" />
            </SelectTrigger>
            <SelectContent>
              {sprints.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name} · {STATE_LABEL[s.state]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Button size="sm" variant="outline" className="h-8" onClick={() => setAdding(true)}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />Спринт
        </Button>
        {sprint && sprint.state === 'planned' && (
          <Button size="sm" className="h-8" disabled={setState.isPending}
            onClick={() => setState.mutate('active')}>
            <Flag className="mr-1.5 h-3.5 w-3.5" />Начать
          </Button>
        )}
        {sprint && sprint.state === 'active' && (
          <Button size="sm" variant="outline" className="h-8" disabled={setState.isPending}
            onClick={() => setState.mutate('closed')}>
            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />Закрыть спринт
          </Button>
        )}
        {sprint && (
          <span className="text-xs text-muted-foreground">
            взято {sprint.taken} · сделано {sprint.done} · осталось {sprint.left}
            {sprint.carried_over > 0 && ` · перенесено ${sprint.carried_over}`}
          </span>
        )}
      </div>

      {adding && (
        <SprintEditor companyId={company.id} projectId={project}
          onClose={() => setAdding(false)}
          onSaved={(s) => { setAdding(false); setSprintId(s.id); refresh() }} />
      )}

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-2">
        <Column title="Бэклог" hint="что решили делать, но не решили когда"
          tasks={backlog} loading={backlogQ.isLoading} error={backlogQ.isError}
          onRetry={() => void backlogQ.refetch()}
          highlight={over === 'backlog' && !!dragged}
          onDragOver={() => setOver('backlog')} onDrop={() => drop('backlog')}
          onDragStart={setDragged} onDragEnd={() => { setDragged(null); setOver(null) }}
          dragged={dragged} onOpen={(id) => navigate(`/docs/company?view=errands&task=${id}`)} />
        <Column
          title={sprint ? `Спринт ${sprint.name}` : 'Спринт'}
          hint={sprint
            ? [sprint.starts_on, sprint.ends_on].filter(Boolean).join(' — ') || STATE_LABEL[sprint.state]
            : 'спринта пока нет: заведите отрезок и перетащите в него работу'}
          tasks={inSprint} loading={sprintQ.isLoading} error={sprintQ.isError}
          onRetry={() => void sprintQ.refetch()}
          highlight={over === 'sprint' && !!dragged && !closed}
          onDragOver={() => setOver('sprint')} onDrop={() => !closed && drop('sprint')}
          onDragStart={setDragged} onDragEnd={() => { setDragged(null); setOver(null) }}
          dragged={dragged} onOpen={(id) => navigate(`/docs/company?view=errands&task=${id}`)} />
      </div>
    </div>
  )
}

function Column({
  title, hint, tasks, loading, error, onRetry, highlight,
  onDragOver, onDrop, onDragStart, onDragEnd, dragged, onOpen,
}: {
  title: string; hint: string
  tasks: SpaceTask[]; loading: boolean; error: boolean; onRetry: () => void
  highlight: boolean
  onDragOver: () => void; onDrop: () => void
  onDragStart: (id: string) => void; onDragEnd: () => void
  dragged: string | null
  onOpen: (id: string) => void
}) {
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); onDragOver() }}
      onDrop={onDrop}
      className={cn('flex min-h-0 flex-col rounded-xl border bg-muted/30 transition-colors',
        highlight && 'border-primary bg-primary/5 ring-1 ring-primary/30')}>
      <div className="flex items-baseline gap-2 px-3 py-2.5">
        <span className="text-[13px] font-medium">{title}</span>
        <span className="flex-1 truncate text-[11px] text-muted-foreground">{hint}</span>
        <span className="rounded-full bg-background px-1.5 py-0.5 text-[11px] tabular-nums text-muted-foreground">
          {tasks.length}
        </span>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
        {loading ? (
          <div className="flex items-center gap-2 p-4 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />Загрузка…
          </div>
        ) : error ? (
          <QueryError message="Список не загрузился" onRetry={onRetry} />
        ) : tasks.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">Пусто.</div>
        ) : tasks.map((t) => (
          <div key={t.id} draggable onDragStart={() => onDragStart(t.id)}
            onDragEnd={onDragEnd} onClick={() => onOpen(t.id)}
            className={cn('group cursor-grab rounded-lg border bg-card px-2.5 py-2 text-xs shadow-sm transition-all active:cursor-grabbing',
              'hover:-translate-y-px hover:border-primary/40 hover:shadow-md',
              dragged === t.id && 'opacity-40 shadow-none',
              t.status !== 'open' && 'opacity-70')}>
            <div className="flex items-start gap-1.5">
              {(t.priority === 'high' || t.priority === 'critical') && (
                <span aria-hidden className={cn('mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                  t.priority === 'critical' ? 'bg-red-500' : 'bg-amber-500')} />
              )}
              <span className={cn('flex-1 font-medium leading-snug',
                t.status !== 'open' && 'line-through')}>
                {t.title}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-muted-foreground/70">
                {taskKey(t)}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
              {t.assignee && <span>{t.assignee}</span>}
              {t.stage && <span>{t.stage}</span>}
              {t.time?.estimate_text && t.time.estimate_text !== '—' && (
                <span>оценка {t.time.estimate_text}</span>
              )}
              {t.fix_version && (
                <Badge variant="outline" className="h-4 px-1 text-[10px]">{t.fix_version}</Badge>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SprintEditor({ companyId, projectId, onClose, onSaved }: {
  companyId: string; projectId: string
  onClose: () => void; onSaved: (s: TaskSprint) => void
}) {
  const [name, setName] = useState('')
  const [startsOn, setStartsOn] = useState('')
  const [endsOn, setEndsOn] = useState('')

  const save = useMutation({
    mutationFn: () => tasksService.createTaskSprint({
      companyId, projectId, name: name.trim(),
      startsOn: startsOn || undefined, endsOn: endsOn || undefined,
    }),
    onSuccess: (s) => { toast.success('Спринт заведён'); onSaved(s) },
    onError: (e) => toast.error((e as Error).message),
  })

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-muted/20 p-3">
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Название</label>
        <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
          placeholder="Спринт 34" className="h-8 w-[200px] text-xs" />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Начало</label>
        <Input type="date" value={startsOn} className="h-8 text-xs"
          onChange={(e) => setStartsOn(e.target.value)} />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Конец</label>
        <Input type="date" value={endsOn} className="h-8 text-xs"
          onChange={(e) => setEndsOn(e.target.value)} />
      </div>
      <Button size="sm" className="h-8" disabled={!name.trim() || save.isPending}
        onClick={() => save.mutate()}>
        {save.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Завести
      </Button>
      <Button size="sm" variant="ghost" className="h-8 px-2" onClick={onClose}>
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

export default SprintPlanPage
