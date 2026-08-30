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
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Check, Eye, ListChecks, Loader2, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { SearchPicker } from '@/components/tasks/SearchPicker'
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

  const [picked, setPicked] = useState<Set<string>>(new Set())
  const people = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })

  /** Действие над пачкой. Идём по одной задаче: у каждой свои права и свой
   *  след, и общий запрос «примени ко всем» их бы обошёл. */
  const bulk = useMutation({
    mutationFn: async (data: (t: SpaceTask) => Parameters<typeof tasksService.taskAction>[1]) => {
      const выбранные = (q.data?.tasks ?? []).filter((t) => picked.has(t.id))
      // Отказ на одной задаче не отменяет остальные и не прячет то, что уже
      // применилось: иначе человек видит старый список, повторяет действие и
      // продлевает половину пачки дважды.
      const итог = await Promise.allSettled(выбранные.map(
        (t) => tasksService.taskAction(t.id, data(t))))
      return {
        done: итог.filter((r) => r.status === 'fulfilled').length,
        total: выбранные.length,
      }
    },
    onSettled: () => { setPicked(new Set()); refresh() },
    onSuccess: ({ done, total }) => {
      if (done === total) toast.success(`Готово: ${done}`)
      else toast.warning(`Применилось ${done} из ${total} — остальные отказали`)
    },
    onError: (e: Error) => toast.error(e.message || 'Не применилось'),
  })

  /** Продлить: от собственного срока задачи, а у бессрочной — от сегодня. */
  const продлить = (дней: number) => bulk.mutate((t) => {
    const от = t.due_at ? new Date(t.due_at) : new Date()
    от.setDate(от.getDate() + дней)
    от.setHours(18, 0, 0, 0)
    return { companyId, dueAt: от.toISOString() }
  })

  const rows = useMemo(() => q.data?.tasks ?? [], [q.data])
  const все = rows.length > 0 && rows.every((t) => picked.has(t.id))

  if (!companyId) return null

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Icon className="h-4.5 w-4.5 text-primary" />{title}
        </h1>
        <p className="mt-0.5 max-w-2xl text-xs text-muted-foreground">{hint}</p>
      </div>

      {/* Панель видна только при выборе: постоянная полоса действий над пустым
          выбором занимает место и предлагает то, чего нет. */}
      {picked.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2">
          <span className="text-sm font-medium text-primary">Выбрано: {picked.size}</span>
          <span className="text-xs text-muted-foreground">продлить на</span>
          {[1, 3, 7].map((d) => (
            <Button key={d} size="sm" variant="outline" className="h-8 px-2 text-xs"
              disabled={bulk.isPending} onClick={() => продлить(d)}>
              {d} дн.
            </Button>
          ))}
          <SearchPicker
            items={(people.data?.people ?? []).map((p) => ({
              id: p.id, name: p.name, party: p.partyType }))}
            value="" onChange={(v) => bulk.mutate(() => ({ companyId, assigneeId: v }))}
            placeholder="Поручить" emptyLabel="Не назначен"
            searchPlaceholder="Фамилия или имя…" className="w-[190px]" />
          <Button size="sm" variant="outline" className="h-8 px-2 text-xs"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate(() => ({ companyId, status: 'done' }))}>
            <Check className="mr-1 h-3.5 w-3.5" />Закрыть
          </Button>
          <Button size="sm" variant="ghost" className="ml-auto h-8 px-2 text-xs"
            onClick={() => setPicked(new Set())}>Снять выбор</Button>
          {bulk.isPending && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
        </div>
      )}

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
          {/* Выбрать всё — там же, где выбирают строку: искать эту кнопку в
              другом месте человек не должен. */}
          <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-1.5">
            <Checkbox aria-label="Выбрать все"
              checked={все && rows.length > 0}
              onCheckedChange={(v) => setPicked(v
                ? new Set(rows.map((t) => t.id))
                : new Set())} />
            <span className="text-xs text-muted-foreground">
              {все && rows.length > 0 ? 'все выбраны' : `строк: ${rows.length}`}
            </span>
          </div>
          {rows.map((t) => (
            <Row key={t.id} task={t} companyId={companyId} busy={close.isPending}
              picked={picked.has(t.id)}
              onPick={() => setPicked((prev) => {
                const next = new Set(prev)
                if (next.has(t.id)) next.delete(t.id)
                else next.add(t.id)
                return next
              })}
              onOpen={() => navigate(`/docs/company?view=errands&task=${t.id}`)}
              onChanged={refresh} onClose={() => close.mutate(t.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ task, companyId, busy, picked, onPick, onOpen, onChanged, onClose }: {
  task: SpaceTask; companyId: string; busy: boolean
  picked: boolean; onPick: () => void
  onOpen: () => void; onChanged: () => void; onClose: () => void
}) {
  const ref = `task:${task.id}`
  return (
    <div className={cn('flex items-center gap-2 border-b px-3 py-2 last:border-b-0 hover:bg-muted/40',
      picked && 'bg-primary/5')}>
      <Checkbox checked={picked} onCheckedChange={onPick}
        aria-label={`Выбрать ${tasksService.taskKey(task)}`} />
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
      {/* Отметка приходит вместе со строкой, поэтому кнопки говорят правду:
          солнце залито у взятого в день, «убрать из подборки» видно только у
          лежащего в ней. Без отметки они врали бы состоянием, и до неё их
          здесь не было. */}
      <PlaceActions companyId={companyId} targetRef={ref} mark={task.mark}
        dueAt={task.due_at} onChanged={onChanged} />
      <Button size="sm" variant="ghost" className="h-8 shrink-0 px-2" disabled={busy}
        title="Закрыть работу" onClick={onClose}>
        <Check className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

export default TaskRows
