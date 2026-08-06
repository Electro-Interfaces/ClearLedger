/**
 * Рабочее место «Задач»: списки разделов «Моя работа» и «Работа компании».
 *
 * Один экран на все пункты: разница между «Сегодня», «На мне» и «Реестром» —
 * это scope и набор доступных фильтров, а не другая таблица. Второй список с
 * теми же колонками расходился бы с первым через месяц.
 *
 * Весь отбор живёт в адресе: на «просрочки у Петрова» можно дать ссылку, а
 * обзор проваливается сюда сменой параметров.
 */
import { useMemo, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, BookmarkPlus, ChevronsUpDown, Download, ListChecks, Loader2,
  Plus, RefreshCw, Search, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import type { SpaceTask, TaskScope } from '@/services/tasksService'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import { TaskCard } from '@/components/tasks/TaskCard'
import {
  PRIORITY_LABEL, PRIORITY_TONE, STATUS_LABEL, WAITING_LABEL, dt, dtT,
} from '@/components/tasks/taskWords'
import { TASKS_VIEWS, tasksRouteOf, useTasksView } from './TasksLayout'
import { TasksBoardPage } from './TasksBoardPage'
import { ViewsSection } from './TasksRegulation'

const nf = new Intl.NumberFormat('ru-RU')
const PAGE = 100

/** Что показывает пункт: разрез работы и нужны ли ему фильтры реестра. */
const VIEW_SCOPE: Record<string, TaskScope> = {
  today: 'today', mine: 'mine', assigned: 'assigned', waiting: 'waiting',
  watching: 'watching', closed: 'closed', registry: 'all', objects: 'all',
}

export function TasksWorkPage() {
  const { company } = useCompany()
  const { pathname } = useLocation()
  const route = tasksRouteOf(pathname)
  const view = useTasksView(route)
  const meta = (TASKS_VIEWS[route] ?? []).find((v) => v.key === view)
  const scope = VIEW_SCOPE[view] ?? 'open'
  // Фильтры и группировка — свойство пункта, а не переключатель на экране:
  // «Сегодня» с фильтром по автору перестало бы отвечать на свой вопрос.
  const full = view === 'registry' || view === 'objects'

  const [params, setParams] = useSearchParams()
  const set = (kv: Record<string, string | null>) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) n.set(k, v); else n.delete(k) }
    // Смена отбора обнуляет страницу: иначе человек видит пустоту на третьей
    // странице списка, в котором теперь десять строк.
    if (!('page' in kv)) n.delete('page')
    return n
  }, { replace: true })

  const objectId = params.get('object') ?? ''
  const typeId = params.get('type') ?? ''
  const assigneeId = params.get('assignee') ?? ''
  const authorId = params.get('author') ?? ''
  const priority = params.get('priority') ?? ''
  const labelId = params.get('label') ?? ''
  const q = params.get('q') ?? ''
  const sort = params.get('sort') ?? (view === 'today' ? 'due' : 'created')
  const page = Math.max(0, Number(params.get('page')) || 0)
  const openId = params.get('task')
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const objectsQ = useQuery({
    queryKey: ['space-objects', company.id],
    queryFn: () => listSpaceObjects(company.id),
    enabled: full, staleTime: 5 * 60 * 1000,
  })
  const typesQ = useQuery({
    queryKey: ['task-types', company.id],
    queryFn: () => tasksService.listTaskTypes(company.id),
    staleTime: 5 * 60 * 1000,
  })
  const peopleQ = useQuery({
    queryKey: ['task-people', company.id],
    queryFn: () => tasksService.listTaskPeople(company.id),
    enabled: full, staleTime: 5 * 60 * 1000,
  })
  const labelsQ = useQuery({
    queryKey: ['task-labels', company.id],
    queryFn: () => tasksService.listTaskLabels(company.id),
    enabled: full, staleTime: 5 * 60 * 1000,
  })

  const filters = {
    objectId: objectId || undefined, typeId: typeId || undefined,
    assigneeId: assigneeId || undefined, authorId: authorId || undefined,
    priority: priority || undefined, labelId: labelId || undefined,
    q: q || undefined, sort, limit: PAGE, offset: page * PAGE,
  }
  const listQ = useQuery({
    queryKey: ['tasks', company.id, scope, filters],
    queryFn: () => tasksService.listTasks(company.id, scope, filters),
    placeholderData: keepPreviousData,
  })
  const tasks = listQ.data?.tasks ?? []
  const total = listQ.data?.total ?? 0
  const hasFilter = !!(objectId || typeId || assigneeId || authorId || priority || labelId || q)

  const refresh = () => { void listQ.refetch(); setPicked(new Set()) }

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          {/* Заголовок экрана = имя пункта: имя продукта уже в шапке и в рельсе. */}
          <h1 className="text-lg font-semibold">{meta?.label ?? 'Задачи'}</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">{meta?.hint}</p>
        </div>
        <div className="flex items-center gap-2">
          {full && (
            <>
              <SaveViewButton companyId={company.id} query={{
                view: 'registry',
                ...(assigneeId && { assignee: assigneeId }),
                ...(authorId && { author: authorId }),
                ...(typeId && { type: typeId }),
                ...(objectId && { object: objectId }),
                ...(priority && { priority }),
                ...(labelId && { label: labelId }),
                ...(q && { q }),
                ...(sort !== 'created' && { sort }),
              }} />
              <Button variant="outline" size="sm" className="h-8"
                disabled={tasks.length === 0}
                onClick={() => exportTasks(tasks, meta?.label ?? 'Задачи')}>
                <Download className="mr-1.5 h-3.5 w-3.5" />Excel
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" className="h-8"
            onClick={refresh} disabled={listQ.isFetching}>
            <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', listQ.isFetching && 'animate-spin')} />
            Обновить
          </Button>
        </div>
      </div>

      {/* Быстрая постановка: заголовок и Enter. Остальное — потом, в карточке. */}
      {view !== 'closed' && view !== 'watching' && (
        <QuickCreate companyId={company.id} onCreated={refresh} />
      )}

      {full && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input defaultValue={q} placeholder="Поиск: №, заголовок, реплики"
              className="h-8 w-[240px] pl-7 text-xs"
              onKeyDown={(e) => {
                if (e.key === 'Enter') set({ q: (e.target as HTMLInputElement).value || null })
              }} />
          </div>
          <Pick value={assigneeId} onChange={(v) => set({ assignee: v })} width={170}
            placeholder="Исполнитель" allLabel="Любой исполнитель"
            items={(peopleQ.data?.people ?? []).map((p) => ({ id: p.id, name: p.name }))} />
          <Pick value={authorId} onChange={(v) => set({ author: v })} width={150}
            placeholder="Автор" allLabel="Любой автор"
            items={(peopleQ.data?.people ?? []).map((p) => ({ id: p.id, name: p.name }))} />
          <Pick value={typeId} onChange={(v) => set({ type: v })} width={150}
            placeholder="Тип" allLabel="Все типы"
            items={(typesQ.data?.types ?? []).map((t) => ({ id: t.id, name: t.name }))} />
          <Pick value={objectId} onChange={(v) => set({ object: v })} width={180}
            placeholder="Объект" allLabel="Все объекты"
            items={(objectsQ.data ?? []).map((o) => ({ id: o.id, name: o.name }))} />
          <Pick value={priority} onChange={(v) => set({ priority: v })} width={140}
            placeholder="Срочность" allLabel="Любая срочность"
            items={Object.entries(PRIORITY_LABEL).map(([id, name]) => ({ id, name }))} />
          <Pick value={labelId} onChange={(v) => set({ label: v })} width={150}
            placeholder="Метка" allLabel="Все метки"
            items={(labelsQ.data?.labels ?? []).map((l) => ({ id: l.id, name: l.name }))} />
          {hasFilter && (
            <Button variant="ghost" size="sm" className="h-8 text-muted-foreground"
              onClick={() => set({
                q: null, assignee: null, author: null, type: null,
                object: null, priority: null, label: null,
              })}>
              <X className="mr-1 h-3.5 w-3.5" />Сбросить
            </Button>
          )}
        </div>
      )}

      {picked.size > 0 && (
        <BulkBar companyId={company.id} ids={[...picked]}
          people={peopleQ.data?.people ?? []}
          onDone={refresh} onCancel={() => setPicked(new Set())} />
      )}

      {listQ.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка задач…
        </div>
      ) : listQ.isError ? (
        <QueryError message="Не удалось загрузить задачи"
          onRetry={() => void listQ.refetch()} />
      ) : tasks.length === 0 ? (
        <EmptyState view={view} hasFilter={hasFilter}
          onReset={() => set({
            q: null, assignee: null, author: null, type: null,
            object: null, priority: null, label: null,
          })} />
      ) : (
        <TasksTable tasks={tasks} sort={sort} onSort={(s) => set({ sort: s })}
          picked={picked} onPick={setPicked} groupByObject={view === 'objects'}
          onOpen={(id) => set({ task: id })} />
      )}

      {total > PAGE && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {nf.format(page * PAGE + 1)}–{nf.format(Math.min((page + 1) * PAGE, total))}
            {' из '}{nf.format(total)}
          </span>
          <span className="flex gap-2">
            <Button variant="outline" size="sm" className="h-7" disabled={page === 0}
              onClick={() => set({ page: String(page - 1) })}>Назад</Button>
            <Button variant="outline" size="sm" className="h-7"
              disabled={(page + 1) * PAGE >= total}
              onClick={() => set({ page: String(page + 1) })}>Дальше</Button>
          </span>
        </div>
      )}

      <Sheet open={!!openId} onOpenChange={(v) => { if (!v) set({ task: null }) }}>
        <SheetContent side="right" className="w-full p-0 sm:max-w-2xl">
          <SheetTitle className="sr-only">Карточка задачи</SheetTitle>
          <SheetDescription className="sr-only">Работа, атрибуты и лента</SheetDescription>
          {openId && (
            <TaskCard id={openId} companyId={company.id} onChanged={() => void listQ.refetch()}
              onOpenOther={(id) => set({ task: id })} />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

/* ── Быстрая постановка ──────────────────────────────────────────────── */

function QuickCreate({ companyId, onCreated }: { companyId: string; onCreated: () => void }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const create = useMutation({
    mutationFn: () => tasksService.createTask({ companyId, title: title.trim() }),
    onSuccess: (t) => {
      toast.success(`Задача №${t.number} поставлена`)
      setTitle('')
      qc.invalidateQueries({ queryKey: ['tasks'] })
      onCreated()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  return (
    <div className="flex items-center gap-2">
      <Input value={title} onChange={(e) => setTitle(e.target.value)}
        placeholder="Что сделать? Enter — поставить, подробности допишете в карточке"
        maxLength={300} className="h-9"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && title.trim().length >= 3 && !create.isPending) create.mutate()
        }} />
      <Button size="sm" className="h-9" disabled={title.trim().length < 3 || create.isPending}
        onClick={() => create.mutate()}>
        {create.isPending
          ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          : <Plus className="mr-1.5 h-3.5 w-3.5" />}
        Поставить
      </Button>
    </div>
  )
}

/* ── Таблица ─────────────────────────────────────────────────────────── */

const COLUMNS: { key: string; label: string; sort?: string }[] = [
  { key: 'number', label: '№', sort: 'number' },
  { key: 'title', label: 'Задача' },
  { key: 'type', label: 'Тип' },
  { key: 'stage', label: 'Стадия' },
  { key: 'assignee', label: 'Исполнитель' },
  { key: 'object', label: 'Объект' },
  { key: 'due', label: 'Срок', sort: 'due' },
  { key: 'updated', label: 'Обновлена', sort: 'updated' },
]

function TasksTable({ tasks, sort, onSort, picked, onPick, groupByObject, onOpen }: {
  tasks: SpaceTask[]; sort: string; onSort: (s: string) => void
  picked: Set<string>; onPick: (s: Set<string>) => void
  groupByObject: boolean; onOpen: (id: string) => void
}) {
  // Место — разрез, а не свойство карточки: в «По объектам» одна и та же задача
  // не размножается, но заголовок группы отвечает на вопрос «что на этой точке».
  const groups = useMemo(() => {
    if (!groupByObject) return [{ name: '', tasks }]
    const acc = new Map<string, SpaceTask[]>()
    for (const t of tasks) {
      const k = t.object ?? 'Без объекта'
      acc.set(k, [...(acc.get(k) ?? []), t])
    }
    return [...acc.entries()].sort((a, b) => a[0].localeCompare(b[0], 'ru'))
      .map(([name, rows]) => ({ name, tasks: rows }))
  }, [tasks, groupByObject])

  const toggle = (id: string) => {
    const next = new Set(picked)
    next.has(id) ? next.delete(id) : next.add(id)
    onPick(next)
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[1000px] text-xs">
        <thead className="bg-muted/40 text-muted-foreground">
          <tr>
            <th className="w-8 p-2.5">
              <Checkbox aria-label="Отметить все"
                checked={tasks.length > 0 && tasks.every((t) => picked.has(t.id))}
                onCheckedChange={(v) => onPick(v ? new Set(tasks.map((t) => t.id)) : new Set())} />
            </th>
            {COLUMNS.map((c) => (
              <th key={c.key} className="p-2.5 text-left font-medium">
                {/* Управление таблицей живёт в таблице: сортировка — в шапке
                    столбца, повторный клик переворачивает. */}
                {c.sort ? (
                  <button type="button" className="inline-flex items-center gap-1 hover:text-foreground"
                    onClick={() => onSort(sort === c.sort ? `-${c.sort}` : c.sort!)}>
                    {c.label}
                    {sort === c.sort ? <ArrowUp className="h-3 w-3" />
                      : sort === `-${c.sort}` ? <ArrowDown className="h-3 w-3" />
                        : <ChevronsUpDown className="h-3 w-3 opacity-40" />}
                  </button>
                ) : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <>
              {g.name && (
                <tr key={`g-${g.name}`} className="border-t bg-muted/20">
                  <td colSpan={COLUMNS.length + 1}
                    className="px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground">
                    {g.name} · {g.tasks.length}
                  </td>
                </tr>
              )}
              {g.tasks.map((t) => (
                <tr key={t.id} tabIndex={0} aria-haspopup="dialog"
                  onClick={() => onOpen(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(t.id) }
                  }}
                  className="cursor-pointer border-t transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                  <td className="p-2.5 align-top" onClick={(e) => e.stopPropagation()}>
                    <Checkbox aria-label={`Отметить №${t.number}`}
                      checked={picked.has(t.id)} onCheckedChange={() => toggle(t.id)} />
                  </td>
                  <td className="whitespace-nowrap p-2.5 align-top font-medium">№{t.number}</td>
                  <td className="p-2.5 align-top">
                    <div className="font-medium text-foreground">{t.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                      <span>{STATUS_LABEL[t.status] ?? t.status}</span>
                      {(t.priority === 'high' || t.priority === 'critical') && (
                        <span className={PRIORITY_TONE[t.priority]}>{PRIORITY_LABEL[t.priority]}</span>
                      )}
                      <span>· автор {t.author ?? '—'}</span>
                      {t.checklist.total > 0 && (
                        <span className="inline-flex items-center gap-0.5">
                          <ListChecks className="h-3 w-3" />
                          {t.checklist.done} из {t.checklist.total}
                        </span>
                      )}
                      {t.subtasks.total > 0 && (
                        <span>· подзадач {t.subtasks.open} из {t.subtasks.total} открыто</span>
                      )}
                      {t.waiting_for === 'external' && (
                        <span className="rounded border border-amber-500/40 bg-amber-500/5 px-1 py-px text-amber-700 dark:text-amber-400">
                          {WAITING_LABEL.external}
                        </span>
                      )}
                      {t.labels.map((l) => (
                        <span key={l.id}
                          className="rounded border border-border/60 bg-muted/40 px-1 py-px">
                          {l.name}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="p-2.5 align-top">
                    {t.type ?? <span className="text-muted-foreground">поручение</span>}
                  </td>
                  <td className="p-2.5 align-top">
                    {t.status === 'open' && t.stage
                      ? <span className="whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px]">{t.stage}</span>
                      : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="p-2.5 align-top">
                    {t.assignee ?? <span className="text-muted-foreground">не назначен</span>}
                  </td>
                  <td className="p-2.5 align-top">{t.object ?? '—'}</td>
                  <td className={cn('whitespace-nowrap p-2.5 align-top',
                    t.overdue && 'font-medium text-red-600 dark:text-red-400')}>
                    {t.overdue ? `просрочена · ${dt(t.due_at)}` : dt(t.due_at)}
                  </td>
                  <td className="whitespace-nowrap p-2.5 align-top text-muted-foreground">
                    {dtT(t.updated_at)}
                  </td>
                </tr>
              ))}
            </>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── Массовые действия ───────────────────────────────────────────────── */

function BulkBar({ companyId, ids, people, onDone, onCancel }: {
  companyId: string; ids: string[]; people: { id: string; name: string }[]
  onDone: () => void; onCancel: () => void
}) {
  const qc = useQueryClient()
  const act = useMutation({
    mutationFn: (data: Parameters<typeof tasksService.tasksBulk>[0]) =>
      tasksService.tasksBulk(data),
    onSuccess: (r) => {
      toast.success(r.skipped.length
        ? `Изменено: ${r.changed}. Пропущено (не ваши): ${r.skipped.join(', ')}`
        : `Изменено задач: ${r.changed}`)
      qc.invalidateQueries({ queryKey: ['tasks'] })
      onDone()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2">
      <span className="text-xs font-medium">Отмечено: {ids.length}</span>
      <Select onValueChange={(v) => act.mutate({ companyId, taskIds: ids, assigneeId: v })}>
        <SelectTrigger className="h-8 w-[180px] text-xs">
          <SelectValue placeholder="Передать" />
        </SelectTrigger>
        <SelectContent>
          {people.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
        </SelectContent>
      </Select>
      <Select onValueChange={(v) => act.mutate({ companyId, taskIds: ids, priority: v })}>
        <SelectTrigger className="h-8 w-[150px] text-xs">
          <SelectValue placeholder="Срочность" />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(PRIORITY_LABEL).map(([k, v]) => (
            <SelectItem key={k} value={k}>{v}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button size="sm" variant="outline" className="h-8" disabled={act.isPending}
        onClick={() => act.mutate({ companyId, taskIds: ids, status: 'done' })}>
        Завершить
      </Button>
      <Button size="sm" variant="ghost" className="h-8 text-muted-foreground" onClick={onCancel}>
        Снять отметки
      </Button>
    </div>
  )
}

/* ── Пустые состояния: экран обязан предлагать действие ──────────────── */

function EmptyState({ view, hasFilter, onReset }: {
  view: string; hasFilter: boolean; onReset: () => void
}) {
  if (hasFilter) {
    return (
      <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
        Под этот отбор задач нет.
        <Button variant="link" size="sm" onClick={onReset}>Сбросить отбор</Button>
      </div>
    )
  }
  const text: Record<string, string> = {
    today: 'Ничего не горит: просроченных задач и сроков на сегодня нет.',
    mine: 'На вас сейчас нет открытых задач.',
    assigned: 'Вы никому ничего не поручили. Поставьте задачу строкой выше и назначьте исполнителя в карточке.',
    waiting: 'Наружу ничего не отдано. Поручить подрядчику письмом можно из карточки — заходить в пространство ему не нужно.',
    watching: 'Вы ни за чем не наблюдаете. Наблюдателем становятся из карточки задачи или когда вас упомянут через @.',
    closed: 'Завершённых задач пока нет.',
    registry: 'В компании ещё нет ни одной задачи. Поставьте первую строкой выше.',
    objects: 'Задач, привязанных к объектам, пока нет.',
  }
  return (
    <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
      {text[view] ?? 'Задач нет.'}
    </div>
  )
}

/* ── Сохранение отбора и выгрузка ────────────────────────────────────── */

function SaveViewButton({ companyId, query }: {
  companyId: string; query: Record<string, string>
}) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [open, setOpen] = useState(false)
  const save = useMutation({
    mutationFn: () => tasksService.createTaskView({ companyId, name: name.trim(), query }),
    onSuccess: () => {
      toast.success('Отбор сохранён — он в пункте «Представления»')
      setOpen(false); setName('')
      qc.invalidateQueries({ queryKey: ['task-views'] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  if (!open) {
    return (
      <Button variant="outline" size="sm" className="h-8" onClick={() => setOpen(true)}>
        <BookmarkPlus className="mr-1.5 h-3.5 w-3.5" />Сохранить отбор
      </Button>
    )
  }
  return (
    <span className="flex items-center gap-1">
      <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus
        placeholder="Название отбора" className="h-8 w-[180px] text-xs" maxLength={120}
        onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) save.mutate() }} />
      <Button size="sm" className="h-8" disabled={!name.trim() || save.isPending}
        onClick={() => save.mutate()}>Сохранить</Button>
      <Button variant="ghost" size="sm" className="h-8" onClick={() => setOpen(false)}>
        <X className="h-3.5 w-3.5" />
      </Button>
    </span>
  )
}

/** Выгрузка видимой страницы. Библиотека тянется лениво — в основной чанк
 *  четыреста килобайт ради кнопки, которую жмут раз в месяц, не кладём. */
async function exportTasks(tasks: SpaceTask[], sheetName: string) {
  const { loadXlsx } = await import('@/utils/xlsxLoader')
  const XLSX = await loadXlsx()
  const rows = tasks.map((t) => ({
    '№': t.number,
    'Задача': t.title,
    'Тип': t.type ?? 'поручение',
    'Стадия': t.stage ?? '',
    'Состояние': STATUS_LABEL[t.status] ?? t.status,
    'Срочность': PRIORITY_LABEL[t.priority] ?? t.priority,
    'Исполнитель': t.assignee ?? '',
    'Автор': t.author ?? '',
    'Объект': t.object ?? '',
    'Срок': t.due_at ? new Date(t.due_at).toLocaleDateString('ru-RU') : '',
    'Просрочена': t.overdue ? 'да' : '',
    'У кого мяч': t.waiting_for === 'external' ? 'внешняя сторона' : 'у нас',
    'Чек-лист': t.checklist.total ? `${t.checklist.done} из ${t.checklist.total}` : '',
    'Метки': t.labels.map((l) => l.name).join(', '),
  }))
  const sheet = XLSX.utils.json_to_sheet(rows)
  const book = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(book, sheet, sheetName.slice(0, 31))
  XLSX.writeFile(book, `Задачи — ${sheetName}.xlsx`)
}

/* ── Мелочи ──────────────────────────────────────────────────────────── */

function Pick({ value, onChange, items, placeholder, allLabel, width }: {
  value: string; onChange: (v: string | null) => void
  items: { id: string; name: string }[]
  placeholder: string; allLabel: string; width: number
}) {
  return (
    <Select value={value || 'all'} onValueChange={(v) => onChange(v === 'all' ? null : v)}>
      <SelectTrigger className="h-8 text-xs" style={{ width }}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{allLabel}</SelectItem>
        {items.map((i) => <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

/** Раздел «Работа компании»: реестр и «По объектам» — тот же список, «Доска» —
 *  своя раскладка. Переключатель здесь, а не в маршруте: пункт раздела живёт в
 *  `?view=`, и отдельный путь под доску завёл бы второе правило навигации. */
export function TasksCompanyPage() {
  const { company } = useCompany()
  const view = useTasksView(tasksRouteOf(useLocation().pathname))
  if (view === 'board') return <TasksBoardPage />
  if (view === 'views') return <ViewsSection companyId={company.id} />
  return <TasksWorkPage />
}

export default TasksWorkPage
