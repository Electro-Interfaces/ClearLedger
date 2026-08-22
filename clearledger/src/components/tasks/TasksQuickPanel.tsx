/**
 * Окно «Трека» из шапки — рабочее место в миниатюре, а не сводка.
 *
 * Раньше здесь был один список «на мне» и приглашение уйти в приложение. Но в
 * шапку заглядывают не за отчётом, а чтобы посмотреть, что горит, отметить
 * сделанное и записать новое, пока не забылось. Поэтому окно умеет четыре разреза,
 * закрывает задачу на месте и ставит новую одной строкой.
 *
 * Что сюда НЕ тащим: маршруты и стадии целиком, историю, отборы по меткам и
 * объектам, командную строку над пачкой. Это работа на весь экран, и она живёт в
 * «Треке» (`/docs`) — кнопка рядом.
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Check, ListChecks, Loader2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useCompany } from '@/contexts/CompanyContext'
import { useSupportContext } from '@/contexts/SupportContext'
import * as tasksService from '@/services/tasksService'
import type { SpaceTask, TaskScope } from '@/services/tasksService'
import { cn } from '@/lib/utils'

/** Срок словами: «сегодня» / «завтра» / «просрочена на 3 дн» — точная дата тут лишняя. */
function dueText(due: string | null, overdue: boolean): string | null {
  if (!due) return null
  const days = Math.round((new Date(due).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000)
  if (days < 0) return `просрочена на ${-days} дн`
  // Срок сегодня, но час уже прошёл: бэкенд пометил задачу просроченной, а разница
  // в днях ещё ноль — «просрочена на 0 дн» тут и вылезала.
  if (overdue) return 'срок истёк'
  if (days === 0) return 'срок сегодня'
  if (days === 1) return 'срок завтра'
  return `срок через ${days} дн`
}

/** Разрезы окна. Те же `scope`, что у списка в приложении: открыв «Трек» следом,
 *  человек видит ровно то же, а не другой набор строк. */
const TABS: { key: TaskScope; label: string; hint: string; empty: string }[] = [
  { key: 'mine', label: 'На мне', hint: 'работа, которую делаю я',
    empty: 'На вас сейчас ничего не назначено.' },
  { key: 'today', label: 'Горит', hint: 'просрочено и срок на носу',
    empty: 'Ничего не горит: сроки не поджимают.' },
  { key: 'assigned', label: 'Я поставил', hint: 'что поручил другим',
    empty: 'Вы пока никому ничего не поручали.' },
  { key: 'watching', label: 'Наблюдаю', hint: 'слежу со стороны',
    empty: 'Вы ни за чем не следите со стороны.' },
]

export function TasksQuickPanel() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { companyId } = useCompany()
  const { closeInteraction } = useSupportContext()
  const [scope, setScope] = useState<TaskScope>('mine')
  const [draft, setDraft] = useState('')

  // Тот же ключ, что у списка в приложении, и у счётчика на кнопке: открыв «Трек»
  // следом, человек видит готовый список, а не второй запрос за теми же строками.
  const { data, isLoading } = useQuery({
    queryKey: ['tasks', companyId, scope, '', '', ''],
    queryFn: () => tasksService.listTasks(companyId, scope),
    enabled: !!companyId,
  })
  // «На мне» и «Я поставил» — про живую работу; закрытые там только шумят. В «Горит»
  // и «Наблюдаю» отбор делает сервер, и второй раз фильтровать нечего.
  const tasks = useMemo(() => {
    const rows = data?.tasks || []
    return scope === 'mine' || scope === 'assigned'
      ? rows.filter((t) => t.status === 'open')
      : rows
  }, [data, scope])
  const overdue = tasks.filter((t) => t.overdue).length

  const refresh = () => qc.invalidateQueries({ queryKey: ['tasks'] })

  const done = useMutation({
    mutationFn: (id: string) => tasksService.taskAction(id, { companyId, status: 'done' }),
    onSuccess: () => { toast.success('Задача закрыта'); refresh() },
    onError: (e) => toast.error((e as Error).message),
  })

  // Быстрая постановка — себе и без срока: окно в шапке существует ровно для того,
  // чтобы мысль не потерялась. Тип, проект, исполнитель и срок проставляются потом
  // в карточке, куда уводит уведомление.
  const add = useMutation({
    mutationFn: () => tasksService.createTask({ companyId, title: draft.trim() }),
    onSuccess: (t: SpaceTask) => {
      setDraft('')
      toast.success(`Задача ${tasksService.taskKey(t)} поставлена`, {
        action: { label: 'Открыть', onClick: () => open(t.id) },
      })
      refresh()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const open = (id?: string) => {
    closeInteraction()
    navigate(id ? `/docs/work?view=errands&task=${id}` : '/docs/work?view=errands')
  }

  const tab = TABS.find((t) => t.key === scope) ?? TABS[0]

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-1">
          {TABS.map((t) => (
            <button key={t.key} type="button" title={t.hint} onClick={() => setScope(t.key)}
              className={cn('rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                scope === t.key
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {isLoading ? 'Загружаю…' : (
              <>
                {tasks.length}
                {overdue > 0 && (
                  <span className="ml-1 font-medium text-red-600">· просрочено {overdue}</span>
                )}
              </>
            )}
          </span>
          <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={() => open()}>
            Открыть «Трек»
            <ArrowUpRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2">
        <Plus className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <Input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={300}
          placeholder="Записать задачу себе — Enter поставит"
          className="h-8 border-0 bg-transparent px-0 text-sm shadow-none focus-visible:ring-0"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim().length >= 3 && !add.isPending) add.mutate()
          }} />
        {add.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загружаю задачи…
        </div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 dark:bg-primary/20">
            <ListChecks className="h-7 w-7 text-primary" />
          </div>
          <p className="max-w-sm text-sm text-muted-foreground">
            {tab.empty} Записать новую можно строкой выше, а вся работа компании —
            в «Треке».
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-2">
          {tasks.map((t) => (
            <div key={t.id}
              className="group flex items-start gap-2 rounded-lg px-2 py-2 transition-colors hover:bg-accent">
              {/* Закрыть на месте может исполнитель — в чужих разрезах галочки нет:
                  она обещала бы действие, которого сервер не даст. */}
              {(scope === 'mine' || scope === 'today') && (
                <button type="button" title="Закрыть задачу"
                  disabled={done.isPending}
                  onClick={() => done.mutate(t.id)}
                  className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border border-border text-transparent transition-colors hover:border-primary hover:text-primary">
                  <Check className="size-3.5" />
                </button>
              )}
              <button type="button" onClick={() => open(t.id)}
                className="flex min-w-0 flex-1 items-start gap-3 text-left">
                <span className="mt-0.5 shrink-0 font-mono text-xs text-muted-foreground">
                  {tasksService.taskKey(t)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">{t.title}</span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                    {t.project && <span className="text-primary/80">{t.project}</span>}
                    {t.stage && <span>{t.stage}</span>}
                    {scope === 'assigned' && t.assignee && <span>· {t.assignee}</span>}
                    {t.object && <span>· {t.object}</span>}
                    {dueText(t.due_at, t.overdue) && (
                      <span className={t.overdue ? 'text-red-600' : ''}>· {dueText(t.due_at, t.overdue)}</span>
                    )}
                  </span>
                </span>
                {(t.priority === 'critical' || t.priority === 'high') && (
                  <Badge variant="outline" className="mt-0.5 h-5 shrink-0 px-1.5 text-[10px]">
                    {t.priority === 'critical' ? 'критично' : 'важно'}
                  </Badge>
                )}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
