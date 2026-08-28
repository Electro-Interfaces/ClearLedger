/**
 * Список поручений строкой — та же подача, что у «Моей очереди».
 *
 * В разделе «Моё» человек всегда спрашивает одно: что за работа и что с ней
 * сделать. Ответ должен выглядеть одинаково, из какого бы разреза он ни пришёл;
 * реестр с колонками, отбором и выделением пачкой отвечает на другой вопрос —
 * «что вообще есть в компании» — и живёт в «Компании».
 *
 * Строка собрана из тех же частей, что строка очереди и строка раскладки:
 * ручка переноса, название с метой, срок, личные действия, закрытие. Четвёртой
 * разновидности строки в продукте нет и не заводится.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Check, Eye, ListChecks, Loader2, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { QueryError } from '@/components/common/QueryError'
import { DragHandle } from '@/components/docs/DragHandle'
import { PlaceActions } from '@/components/docs/PlaceActions'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import type { SpaceTask, TaskScope } from '@/services/tasksService'
import { dt } from '@/components/tasks/taskWords'
import { cn } from '@/lib/utils'

export function TaskRows({ scope, title, hint, empty, icon: Icon = ListChecks }: {
  scope: TaskScope
  title: string
  hint: string
  empty: string
  icon?: typeof ListChecks
}) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const companyId = company?.id ?? ''

  const q = useQuery({
    queryKey: ['tasks', companyId, scope, '', '', ''],
    queryFn: () => tasksService.listTasks(companyId, scope),
    enabled: !!companyId,
  })
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['tasks'] })
    void qc.invalidateQueries({ queryKey: ['work-mine'] })
  }
  const close = useMutation({
    mutationFn: (id: string) => tasksService.taskAction(id, { companyId, status: 'done' }),
    onSuccess: () => { refresh(); toast.success('Закрыто') },
    onError: (e: Error) => toast.error(e.message || 'Не закрылось'),
  })

  if (!companyId) return null
  const rows = q.data?.tasks ?? []

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Icon className="h-4.5 w-4.5 text-primary" />{title}
        </h1>
        <p className="mt-0.5 max-w-2xl text-xs text-muted-foreground">{hint}</p>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Собираем список…
        </div>
      ) : q.isError ? (
        <QueryError message="Список не загрузился" onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted-foreground">
          {empty}
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          {rows.map((t) => (
            <Row key={t.id} task={t} companyId={companyId} busy={close.isPending}
              onOpen={() => navigate(`/docs/company?view=errands&task=${t.id}`)}
              onChanged={refresh} onClose={() => close.mutate(t.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ task, companyId, busy, onOpen, onChanged, onClose }: {
  task: SpaceTask; companyId: string; busy: boolean
  onOpen: () => void; onChanged: () => void; onClose: () => void
}) {
  const ref = `task:${task.id}`
  return (
    <div className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0 hover:bg-muted/40">
      <DragHandle targetRef={ref} label={`${tasksService.taskKey(task)} ${task.title}`} />
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="truncate text-sm leading-snug">{task.title}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          <span className="font-mono">{tasksService.taskKey(task)}</span>
          {task.stage && <span>{task.stage}</span>}
          {task.assignee
            ? <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" />{task.assignee}</span>
            : <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                <UserPlus className="h-3 w-3" />никому не поручено
              </span>}
        </div>
      </button>
      <span className={cn('shrink-0 text-xs tabular-nums',
        task.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
        {task.due_at ? dt(task.due_at) : 'без срока'}
      </span>
      <PlaceActions companyId={companyId} targetRef={ref} mark={undefined}
        onChanged={onChanged} />
      <Button size="sm" variant="ghost" className="h-8 shrink-0 px-2" disabled={busy}
        title="Закрыть работу" onClick={onClose}>
        <Check className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

export default TaskRows
