/**
 * Разбор — работа, у которой нет исполнителя.
 *
 * Такое поручение существует, но не лежит ни в чьей очереди: заведено «в
 * компанию», пришло письмом, родилось из чата или из показателя «Пульса». Пока
 * его никто не взял, спрашивать не с кого, а сроки идут. Место, где эта работа
 * видна всем сразу, и есть разбор — тот же приём, что Triage у Linear: входящее
 * не должно засорять рабочий список, но и пропадать не должно.
 *
 * Четыре решения, и все — одним нажатием в строке: беру себе, поручаю другому,
 * закрываю как ненужное, откладываю у себя. Открывать карточку ради этого не
 * нужно — иначе разбор превращается в отдельную работу, которой не занимаются.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Check, Loader2, UserCheck, UserPlus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { QueryError } from '@/components/common/QueryError'
import { SearchPicker } from '@/components/tasks/SearchPicker'
import { DragHandle } from '@/components/docs/DragHandle'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import type { SpaceTask } from '@/services/tasksService'
import { dt } from '@/components/tasks/taskWords'
import { cn } from '@/lib/utils'

export function TriagePage() {
  const { company } = useCompany()
  const { user } = useAuth()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const companyId = company?.id ?? ''

  const q = useQuery({
    queryKey: ['tasks', companyId, 'triage', '', '', ''],
    queryFn: () => tasksService.listTasks(companyId, 'triage'),
    enabled: !!companyId,
  })
  const people = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['tasks'] })
    void qc.invalidateQueries({ queryKey: ['work-mine'] })
    void qc.invalidateQueries({ queryKey: ['work'] })
  }

  const act = useMutation({
    mutationFn: ({ id, data }: {
      id: string; data: Parameters<typeof tasksService.taskAction>[1]
    }) => tasksService.taskAction(id, data),
    onSuccess: () => { refresh(); toast.success('Разобрано') },
    onError: (e: Error) => toast.error(e.message || 'Не получилось'),
  })

  if (!companyId) return null

  const rows = q.data?.tasks ?? []

  return (
    <div className="flex h-full min-h-0 w-full max-w-5xl flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="text-lg font-semibold text-foreground">Разбор</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Работа без исполнителя: заведена, но ни у кого не в очереди. Возьмите
          себе, поручите или закройте — сроки по ней идут уже сейчас.
        </p>
      </header>

      {q.isError && (
        <QueryError message="Разбор не загрузился" error={q.error} onRetry={() => void q.refetch()} />
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {q.isLoading ? (
          <div className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />Смотрим, что не разобрано…
          </div>
        ) : rows.length === 0 ? (
          <p className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted-foreground">
            Разбирать нечего: у всей живой работы есть исполнитель.
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border">
            {rows.map((t) => (
              <TriageRow key={t.id} task={t} companyId={companyId}
                me={user?.id ?? ''} people={people.data?.people ?? []}
                busy={act.isPending}
                onOpen={() => navigate(`/docs/company?view=errands&task=${t.id}`)}
                onAct={(data) => act.mutate({ id: t.id, data })} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TriageRow({ task, companyId, me, people, busy, onOpen, onAct }: {
  task: SpaceTask
  companyId: string
  me: string
  people: tasksService.TaskPerson[]
  busy: boolean
  onOpen: () => void
  onAct: (data: Parameters<typeof tasksService.taskAction>[1]) => void
}) {
  const [комуОткрыт, setКомуОткрыт] = useState(false)
  const [причина, setПричина] = useState<string | null>(null)

  return (
    <div className="border-b px-3 py-2 last:border-b-0 hover:bg-muted/40">
      <div className="flex items-center gap-2">
        <DragHandle targetRef={`task:${task.id}`}
          label={`${tasksService.taskKey(task)} ${task.title}`} />
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
          <div className="truncate text-sm">{task.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span className="font-mono">{tasksService.taskKey(task)}</span>
            {task.author && <span>завёл: {task.author}</span>}
            {task.type && <span>{task.type}</span>}
          </div>
        </button>
        <span className={cn('shrink-0 text-xs tabular-nums',
          task.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
          {task.due_at ? dt(task.due_at) : 'без срока'}
        </span>

        {/* Четыре решения в строке. Открывать карточку ради «беру себе» — то,
            из-за чего разбор перестают делать. */}
        <Button size="sm" variant="outline" className="h-8 shrink-0 px-2 text-xs"
          disabled={busy} title="Взять работу на себя"
          onClick={() => onAct({ companyId, assigneeId: me })}>
          <UserCheck className="mr-1 h-3.5 w-3.5" />Беру
        </Button>
        <Button size="sm" variant="ghost" className="h-8 shrink-0 px-2 text-xs"
          disabled={busy} title="Поручить другому"
          onClick={() => setКомуОткрыт((v) => !v)}>
          <UserPlus className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" className="h-8 shrink-0 px-2 text-xs"
          disabled={busy} title="Закрыть как ненужное — с причиной"
          onClick={() => setПричина('')}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {комуОткрыт && (
        <div className="mt-2 flex items-center gap-2 pl-6">
          <SearchPicker
            items={people.map((p) => ({ id: p.id, name: p.name, party: p.partyType }))}
            value="" onChange={(v) => { onAct({ companyId, assigneeId: v }); setКомуОткрыт(false) }}
            placeholder="Кому поручить" emptyLabel="Не назначен"
            searchPlaceholder="Фамилия или имя…" />
        </div>
      )}

      {причина !== null && (
        // Закрытие без причины — потерянная работа: через месяц никто не вспомнит,
        // почему её не сделали, и заведут заново.
        <div className="mt-2 flex items-center gap-2 pl-6">
          <Input value={причина} autoFocus placeholder="Почему закрываем"
            className="h-8 max-w-sm text-xs"
            onChange={(e) => setПричина(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && причина.trim()) {
                onAct({ companyId, status: 'cancelled', note: причина.trim() })
                setПричина(null)
              }
              if (e.key === 'Escape') setПричина(null)
            }} />
          <Button size="sm" className="h-8 px-2 text-xs" disabled={!причина.trim()}
            onClick={() => {
              onAct({ companyId, status: 'cancelled', note: причина.trim() })
              setПричина(null)
            }}>
            <Check className="mr-1 h-3.5 w-3.5" />Закрыть
          </Button>
          <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
            onClick={() => setПричина(null)}>Отмена</Button>
        </div>
      )}
    </div>
  )
}

export default TriagePage
