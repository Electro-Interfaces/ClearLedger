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
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, BookmarkPlus, CheckCircle2, ChevronsUpDown, Clock, Download,
  GitBranch, ListChecks, Loader2, Plus, RefreshCw, Search, Terminal, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import type { ListedTask, TaskScope } from '@/services/tasksService'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import { TaskCard } from '@/components/tasks/TaskCard'
import { NewTaskDialog } from '@/components/tasks/NewTaskDialog'
import { SearchPicker } from '@/components/tasks/SearchPicker'
import {
  PRIORITY_LABEL, PRIORITY_TONE, STATUS_LABEL, dt, dtT,
} from '@/components/tasks/taskWords'
import { TASKS_VIEWS, tasksRouteOf, useTasksView } from './TasksLayout'
import { TasksBoardPage } from './TasksBoardPage'
import { ViewsSection } from './TasksRegulation'
import { TasksDueBoard } from './TasksDueBoard'

const nf = new Intl.NumberFormat('ru-RU')
const PAGE = 100

/** Что показывает пункт: разрез работы и нужны ли ему фильтры реестра. */
const VIEW_SCOPE: Record<string, TaskScope> = {
  today: 'today', mine: 'mine', assigned: 'assigned', waiting: 'waiting',
  watching: 'watching', closed: 'closed', registry: 'all', objects: 'all',
}

export function TasksWorkPage({ embeddedView }: {
  embeddedView?: 'mine' | 'registry'
} = {}) {
  const { company } = useCompany()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const route = tasksRouteOf(pathname)
  const routedView = useTasksView(route)
  const view = embeddedView ?? routedView
  const meta = embeddedView === 'mine'
    ? { label: 'Поручения', hint: 'Работа, которую выполняю я' }
    : embeddedView === 'registry'
      ? { label: 'Поручения компании', hint: 'Вся работа с отбором, поиском и выгрузкой' }
      : (TASKS_VIEWS[route] ?? []).find((item) => item.key === view)
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
  const projectId = params.get('project') ?? ''
  const versionId = params.get('version') ?? ''
  const typeId = params.get('type') ?? ''
  const assigneeId = params.get('assignee') ?? ''
  const authorId = params.get('author') ?? ''
  const priority = params.get('priority') ?? ''
  const labelId = params.get('label') ?? ''
  const q = params.get('q') ?? ''
  const sort = params.get('sort') ?? (view === 'today' ? 'due' : 'created')
  const page = Math.max(0, Number(params.get('page')) || 0)
  const openId = params.get('task')
  // Личные разделы умеют показываться доской по срокам: вопрос к своей работе
  // не «на каком шаге», а «что сегодня, что на неделе».
  const asBoard = params.get('as') === 'board'
  const canBoard = ['mine', 'assigned', 'today', 'waiting'].includes(view)
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const objectsQ = useQuery({
    queryKey: ['space-objects', company.id],
    queryFn: () => listSpaceObjects(company.id),
    enabled: full, staleTime: 5 * 60 * 1000,
  })
  const projectsQ = useQuery({
    queryKey: ['task-projects', company.id],
    queryFn: () => tasksService.listTaskProjects(company.id),
    staleTime: 5 * 60 * 1000,
  })
  // Версии живут на проекте: отбор по версии показывается, только когда проект
  // выбран, иначе в списке смешались бы одноимённые версии разных продуктов.
  const versionsQ = useQuery({
    queryKey: ['task-versions', company.id, projectId],
    queryFn: () => tasksService.listTaskVersions(company.id, projectId),
    enabled: !!projectId, staleTime: 5 * 60 * 1000,
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
    objectId: objectId || undefined, projectId: projectId || undefined,
    fixVersionId: versionId || undefined,
    typeId: typeId || undefined,
    assigneeId: assigneeId || undefined, authorId: authorId || undefined,
    priority: priority || undefined, labelId: labelId || undefined,
    q: q || undefined, sort, limit: PAGE, offset: page * PAGE,
  }
  const listQ = useQuery({
    queryKey: ['tasks', company.id, scope, filters],
    queryFn: () => tasksService.listTasks(company.id, scope, filters),
    placeholderData: keepPreviousData,
  })
  // Один дешёвый запрос на весь продукт: спрашиваем только счётчик.
  const anyQ = useQuery({
    queryKey: ['tasks-any', company.id],
    queryFn: () => tasksService.listTasks(company.id, 'all', { limit: 1 }),
    staleTime: 5 * 60 * 1000,
  })
  const tasks = listQ.data?.tasks ?? []
  const total = listQ.data?.total ?? 0
  const hasFilter = !!(objectId || projectId || versionId || typeId || assigneeId
                       || authorId || priority || labelId || q)

  const refresh = () => { void listQ.refetch(); setPicked(new Set()) }

  /* Работа с клавиатуры — то, чем берёт YouTrack: `/` в поиск, стрелки по списку,
     Enter открывает, Esc снимает отметки. Клавиши молчат, пока курсор в поле
     ввода: иначе буква «н» в заголовке задачи открывала бы новую задачу. */
  const searchRef = useRef<HTMLInputElement>(null)
  const [cursor, setCursor] = useState(-1)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const typing = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
        || el.isContentEditable)
      if (typing) {
        if (e.key === 'Escape') el?.blur()
        return
      }
      if (e.ctrlKey || e.altKey || e.metaKey) return
      if (e.key === '/') { e.preventDefault(); searchRef.current?.focus(); return }
      if (e.key === 'Escape' && picked.size) { setPicked(new Set()); return }
      if (!tasks.length) return
      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault()
        setCursor((i) => Math.min(tasks.length - 1, i + 1))
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        setCursor((i) => Math.max(0, i - 1))
      } else if (e.key === 'Enter' && cursor >= 0 && cursor < tasks.length) {
        e.preventDefault()
        set({ task: tasks[cursor].id })
      } else if (e.key === ' ' && cursor >= 0 && cursor < tasks.length) {
        // Пробел отмечает строку под курсором — так набирают пачку под команду.
        e.preventDefault()
        const next = new Set(picked)
        const id = tasks[cursor].id
        next.has(id) ? next.delete(id) : next.add(id)
        setPicked(next)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  // Открытая задача занимает экран целиком: это рабочее место, а не всплывающая
  // справка. Возврат — кнопкой «к списку», отбор при этом сохраняется в адресе.
  if (openId) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <TaskCard id={openId} companyId={company.id}
          onChanged={() => void listQ.refetch()}
          onOpenOther={(id) => set({ task: id })}
          onBack={() => set({ task: null })} />
      </div>
    )
  }

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
                ...(projectId && { project: projectId }),
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
          {canBoard && (
            <div className="flex h-8 items-center rounded-md border p-0.5">
              {([['list', 'Список'], ['board', 'Доска']] as const).map(([k, label]) => (
                <button key={k} type="button"
                  onClick={() => set({ as: k === 'board' ? 'board' : null })}
                  className={cn('h-7 rounded px-2.5 text-xs transition-colors',
                    (k === 'board') === asBoard
                      ? 'bg-primary/10 font-medium text-primary'
                      : 'text-muted-foreground hover:text-foreground')}>
                  {label}
                </button>
              ))}
            </div>
          )}
          <Button variant="outline" size="sm" className="h-8"
            onClick={refresh} disabled={listQ.isFetching}>
            <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', listQ.isFetching && 'animate-spin')} />
            Обновить
          </Button>
        </div>
      </div>

      {/* Две постановки рядом: строкой — поймать мысль на ходу, формой — задать
          исполнителя, срок, описание и приложить скриншот сразу. */}
      {view !== 'closed' && view !== 'watching' && (
        <div className="flex items-center gap-2">
          <QuickCreate companyId={company.id} onCreated={refresh} />
          <NewTaskDialog companyId={company.id} defaultObjectId={objectId || undefined}
            onCreated={(id) => { refresh(); set({ task: id }) }} />
        </div>
      )}

      {full && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input defaultValue={q} ref={searchRef}
              placeholder="Поиск: №, заголовок, реплики — «/» ставит курсор сюда"
              className="h-8 w-[240px] pl-7 text-xs"
              onKeyDown={(e) => {
                if (e.key === 'Enter') set({ q: (e.target as HTMLInputElement).value || null })
              }} />
          </div>
          <SearchPicker className="w-[170px]" value={assigneeId}
            onChange={(v) => set({ assignee: v || null })}
            items={(peopleQ.data?.people ?? []).map((p) => ({ id: p.id, name: p.name }))}
            placeholder="Любой исполнитель" emptyLabel="Любой исполнитель"
            searchPlaceholder="Фамилия…" />
          <SearchPicker className="w-[150px]" value={authorId}
            onChange={(v) => set({ author: v || null })}
            items={(peopleQ.data?.people ?? []).map((p) => ({ id: p.id, name: p.name }))}
            placeholder="Любой автор" emptyLabel="Любой автор"
            searchPlaceholder="Фамилия…" />
          {(projectsQ.data?.projects ?? []).length > 0 && (
            <Pick value={projectId} onChange={(v) => set({ project: v, version: null })} width={170}
              placeholder="Проект" allLabel="Все проекты"
              items={(projectsQ.data?.projects ?? []).map((p) => ({
                id: p.id, name: `${p.code} · ${p.name}` }))} />
          )}
          {(versionsQ.data?.versions ?? []).length > 0 && (
            <Pick value={versionId} onChange={(v) => set({ version: v })} width={160}
              placeholder="Версия" allLabel="Любая версия"
              items={(versionsQ.data?.versions ?? []).map((v) => ({ id: v.id, name: v.name }))} />
          )}
          <Pick value={typeId} onChange={(v) => set({ type: v })} width={150}
            placeholder="Тип" allLabel="Все типы"
            items={(typesQ.data?.types ?? [])
              /* Типы чужого проекта в отборе только мешают: их задач в списке нет */
              .filter((x) => !x.project_id || x.project_id === projectId)
              .map((x) => ({ id: x.id, name: x.name }))} />
          <SearchPicker className="w-[200px]" value={objectId}
            onChange={(v) => set({ object: v || null })}
            items={(objectsQ.data ?? []).map((o) => ({
              id: o.id, name: o.name, hint: o.address }))}
            placeholder="Все объекты" emptyLabel="Все объекты"
            searchPlaceholder="Номер, название или адрес…"
            loading={objectsQ.isLoading} width="w-[340px]" />
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
                object: null, priority: null, label: null, version: null,
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
          companyTotal={anyQ.data?.total ?? 1}
          onGo={(path) => navigate(path)}
          onReset={() => set({
            q: null, assignee: null, author: null, type: null,
            object: null, priority: null, label: null,
          })} />
      ) : (
        asBoard && canBoard ? (
          <TasksDueBoard tasks={tasks} companyId={company.id}
            onOpen={(id) => set({ task: id })} onChanged={refresh} />
        ) : (
          <TasksTable tasks={tasks} sort={sort} onSort={(s) => set({ sort: s })}
            picked={picked} onPick={setPicked} cursor={cursor} groupByObject={view === 'objects'}
            onOpen={(id) => set({ task: id })} />
        )
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
      toast.success(`Задача ${tasksService.taskKey(t)} поставлена`)
      setTitle('')
      qc.invalidateQueries({ queryKey: ['tasks'] })
      onCreated()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  return (
    <div className="flex flex-1 items-center gap-2">
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
  { key: 'number', label: 'Задача', sort: 'number' },
  { key: 'title', label: 'Задача' },
  { key: 'type', label: 'Тип' },
  { key: 'stage', label: 'Стадия' },
  { key: 'assignee', label: 'Исполнитель' },
  { key: 'object', label: 'Объект' },
  { key: 'due', label: 'Срок', sort: 'due' },
  { key: 'updated', label: 'Обновлена', sort: 'updated' },
]

function TasksTable({ tasks, sort, onSort, picked, onPick, cursor, groupByObject, onOpen }: {
  tasks: ListedTask[]; sort: string; onSort: (s: string) => void
  picked: Set<string>; onPick: (s: Set<string>) => void; cursor?: number
  groupByObject: boolean; onOpen: (id: string) => void
}) {
  // Место — разрез, а не свойство карточки: в «По объектам» одна и та же задача
  // не размножается, но заголовок группы отвечает на вопрос «что на этой точке».
  const groups = useMemo(() => {
    if (!groupByObject) return [{ name: '', tasks }]
    const acc = new Map<string, ListedTask[]>()
    for (const t of tasks) {
      const k = t.object ?? 'Без объекта'
      acc.set(k, [...(acc.get(k) ?? []), t])
    }
    return [...acc.entries()].sort((a, b) => a[0].localeCompare(b[0], 'ru'))
      .map(([name, rows]) => ({ name, tasks: rows }))
  }, [tasks, groupByObject])

  const toggle = (id: string) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else next.add(id)
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
                  ref={(el) => {
                    /* Строку под курсором держим в поле зрения: иначе стрелка
                       уводит выделение за нижний край и человек жмёт вслепую. */
                    if (el && cursor != null && tasks[cursor]?.id === t.id) {
                      el.scrollIntoView({ block: 'nearest' })
                    }
                  }}
                  onClick={() => onOpen(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(t.id) }
                  }}
                  className={cn('cursor-pointer border-t transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                    cursor != null && tasks[cursor]?.id === t.id && 'bg-primary/10')}>
                  <td className="p-2.5 align-top" onClick={(e) => e.stopPropagation()}>
                    <Checkbox aria-label={`Отметить ${tasksService.taskKey(t)}`}
                      checked={picked.has(t.id)} onCheckedChange={() => toggle(t.id)} />
                  </td>
                  <td className="whitespace-nowrap p-2.5 align-top font-medium">
                    {tasksService.taskKey(t)}
                  </td>
                  {/* Строка несла восемь подписей одним кеглем — статус, срочность,
                      автор, чек-лист, подзадачи, время, метки, «ждём внешних», — и
                      читать её было нечем. Убраны дубли колонок (статус, автор), а
                      остальное разведено по весу: слева то, что требует внимания,
                      справа — тихая справка. */}
                  <td className="p-2.5 align-top">
                    <div className="flex items-start gap-1.5">
                      {(t.priority === 'high' || t.priority === 'critical') && (
                        // Срочность — засечкой у самого заголовка: цветное слово в
                        // ряду других слов терялось.
                        <span aria-hidden
                          className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full',
                            t.priority === 'critical' ? 'bg-red-500' : 'bg-amber-500')} />
                      )}
                      <span className="font-medium text-foreground">{t.title}</span>
                      {t.waiting_for === 'external' && (
                        <span className="mt-px shrink-0 rounded border border-amber-500/40 bg-amber-500/5 px-1 py-px text-[10px] text-amber-700 dark:text-amber-400">
                          ждём внешних
                        </span>
                      )}
                    </div>
                    {(t.checklist.total > 0 || t.subtasks.total > 0 || t.time.spent > 0
                      || t.labels.length > 0
                      || t.priority === 'high' || t.priority === 'critical') && (
                      <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-muted-foreground">
                        {(t.priority === 'high' || t.priority === 'critical') && (
                          <span className={PRIORITY_TONE[t.priority]}>
                            {PRIORITY_LABEL[t.priority]}
                          </span>
                        )}
                        {t.checklist.total > 0 && (
                          <span className="inline-flex items-center gap-1">
                            <ListChecks className="h-3 w-3" />
                            {t.checklist.done}/{t.checklist.total}
                          </span>
                        )}
                        {t.subtasks.total > 0 && (
                          <span className="inline-flex items-center gap-1">
                            <GitBranch className="h-3 w-3" />
                            {t.subtasks.total - t.subtasks.open}/{t.subtasks.total}
                          </span>
                        )}
                        {t.time.spent > 0 && (
                          <span className={cn('inline-flex items-center gap-1',
                            t.time.estimate != null && t.time.spent > t.time.estimate
                              && 'text-amber-600 dark:text-amber-400')}>
                            <Clock className="h-3 w-3" />
                            {t.time.spent_text}
                            {t.time.estimate != null && ` / ${t.time.estimate_text}`}
                          </span>
                        )}
                        {/* Две метки и счётчик: полный список меток съедал строку. */}
                        {t.labels.slice(0, 2).map((l) => (
                          <span key={l.id}
                            className="rounded border border-border/60 bg-muted/40 px-1 py-px">
                            {l.name}
                          </span>
                        ))}
                        {t.labels.length > 2 && (
                          <span title={t.labels.map((l) => l.name).join(', ')}>
                            +{t.labels.length - 2}
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="p-2.5 align-top">
                    {t.type ?? <span className="text-muted-foreground">поручение</span>}
                  </td>
                  <td className="p-2.5 align-top">
                    {t.status === 'open' && t.stage ? (
                      <span className="whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px]">
                        {t.stage}
                      </span>
                    ) : (
                      // Закрытая задача: состояние важнее несуществующей стадии.
                      <span className={cn('whitespace-nowrap text-[11px]',
                        t.status === 'done'
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-muted-foreground')}>
                        {STATUS_LABEL[t.status] ?? t.status}
                      </span>
                    )}
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
      <CommandLine companyId={companyId} ids={ids} onDone={onDone} />
    </div>
  )
}

/**
 * Команда одной строкой — как в YouTrack: «на меня срочная срок завтра».
 *
 * Быстрее выпадающих списков там, где надо изменить сразу несколько свойств у
 * пачки задач. Неузнанные слова сервер возвращает списком, и мы их показываем:
 * молчание здесь опаснее отказа — человек уверен, что срок поставлен.
 */
function CommandLine({ companyId, ids, onDone }: {
  companyId: string; ids: string[]; onDone: () => void
}) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const run = useMutation({
    mutationFn: () => tasksService.applyCommand({
      companyId, taskIds: ids, command: text.trim(),
    }),
    onSuccess: (r) => {
      if (r.unknown.length) toast.warning(`Не понял: ${r.unknown.join(', ')}`)
      if (r.skipped.length) toast.warning(`Пропущено: ${r.skipped.join('; ')}`)
      if (r.changed) toast.success(`Изменено задач: ${r.changed}`)
      setText('')
      qc.invalidateQueries({ queryKey: ['tasks'] })
      onDone()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  return (
    <span className="flex min-w-[280px] flex-1 items-center gap-1">
      <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <Input value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Команда: на меня срочная срок завтра"
        title="Примеры: «на меня», «срочная», «проект TF», «стадия Диагностика», «срок через 3 дня», «метка стройка», «время 2ч», «выполнена»"
        className="h-8 flex-1 text-xs"
        onKeyDown={(e) => { if (e.key === 'Enter' && text.trim()) run.mutate() }} />
      <Button size="sm" variant="outline" className="h-8"
        disabled={!text.trim() || run.isPending} onClick={() => run.mutate()}>
        {run.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Применить'}
      </Button>
    </span>
  )
}

/* ── Пустые состояния: экран обязан предлагать действие ──────────────── */

/**
 * Пустой экран — это не «нет данных», а развилка: человек либо пришёл первым
 * и не знает, с чего начать, либо всё сделано и он ищет, куда посмотреть
 * дальше. Ответ на эти два вопроса разный, поэтому и экран разный.
 */
function EmptyState({ view, hasFilter, onReset, companyTotal, onGo }: {
  view: string; hasFilter: boolean; onReset: () => void
  /** Сколько задач в компании вообще — отличает первый запуск от «всё сделано». */
  companyTotal: number
  onGo: (path: string) => void
}) {
  if (hasFilter) {
    return (
      <div className="rounded-lg border border-dashed p-10 text-center">
        <p className="text-sm text-muted-foreground">Под этот отбор задач нет.</p>
        <Button variant="outline" size="sm" className="mt-3" onClick={onReset}>
          Сбросить отбор
        </Button>
      </div>
    )
  }

  // Первый запуск: в компании нет ни одной задачи. Здесь нельзя отвечать
  // «задач нет» — это правда, но бесполезная: человеку надо показать, с чего
  // продукт начинается.
  if (companyTotal === 0) {
    return (
      <div className="rounded-lg border border-dashed p-10 text-center">
        <ListChecks className="mx-auto h-7 w-7 text-muted-foreground/60" />
        <h2 className="mt-3 text-base font-medium">Здесь будет работа компании</h2>
        <p className="mx-auto mt-1.5 max-w-md text-sm text-muted-foreground">
          Поставьте первую задачу строкой выше — одного заголовка достаточно,
          остальное допишете в карточке. Кому и к какому сроку — в форме
          «Поставить подробно».
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <Button variant="outline" size="sm"
            onClick={() => onGo('/tasks/setup?view=types')}>
            Завести типы и маршруты
          </Button>
          <Button variant="ghost" size="sm" className="text-muted-foreground"
            onClick={() => onGo('/tasks/setup?view=recurrences')}>
            Настроить повторяющиеся
          </Button>
        </div>
      </div>
    )
  }

  // Работа в компании есть, а на этом экране пусто — значит человек всё сделал
  // или смотрит не туда. Даём и похвалу, и следующий шаг.
  const done: Record<string, { title: string; hint: string; go?: [string, string] }> = {
    today: {
      title: 'Сегодня ничего не горит',
      hint: 'Просроченных задач нет, сроков на сегодня и завтра тоже.',
      go: ['Посмотреть всё, что на мне', '/tasks?view=mine'],
    },
    mine: {
      title: 'На вас нет открытых задач',
      hint: 'Работа появится здесь, когда вам её поручат — или поставьте себе сами.',
      go: ['Что я поручил другим', '/tasks?view=assigned'],
    },
    assigned: {
      title: 'Вы никому ничего не поручили',
      hint: 'Поставьте задачу и назначьте исполнителя — здесь будет видно, у кого мяч.',
    },
    waiting: {
      title: 'Наружу ничего не отдано',
      hint: 'Подрядчику можно поручить письмом прямо из карточки — заходить в пространство ему не нужно.',
    },
    watching: {
      title: 'Вы ни за чем не наблюдаете',
      hint: 'Наблюдателем становятся из карточки задачи или когда вас упомянут через @.',
    },
    closed: {
      title: 'Завершённых задач пока нет',
      hint: 'Здесь будет видно, что сделано за период.',
    },
    registry: {
      title: 'Под этот разрез задач нет',
      hint: 'Попробуйте другой отбор или посмотрите доску.',
      go: ['Открыть доску', '/tasks/company?view=board'],
    },
    objects: {
      title: 'К объектам работа не привязана',
      hint: 'Объект указывают в форме постановки или в карточке — тогда задача попадёт в этот разрез.',
    },
  }
  const cur = done[view] ?? { title: 'Задач нет', hint: '' }
  return (
    <div className="rounded-lg border border-dashed p-10 text-center">
      <CheckCircle2 className="mx-auto h-7 w-7 text-emerald-500/60" />
      <h2 className="mt-3 text-base font-medium">{cur.title}</h2>
      {cur.hint && (
        <p className="mx-auto mt-1.5 max-w-md text-sm text-muted-foreground">{cur.hint}</p>
      )}
      {cur.go && (
        <Button variant="outline" size="sm" className="mt-4"
          onClick={() => onGo(cur.go![1])}>{cur.go[0]}</Button>
      )}
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
async function exportTasks(tasks: ListedTask[], sheetName: string) {
  const { loadXlsx } = await import('@/utils/xlsxLoader')
  const XLSX = await loadXlsx()
  const rows = tasks.map((t) => ({
    '№': tasksService.taskKey(t),
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
export function TasksCompanyPage({ embeddedView }: {
  embeddedView?: 'registry' | 'board' | 'views'
} = {}) {
  const { company } = useCompany()
  const routedView = useTasksView(tasksRouteOf(useLocation().pathname))
  const view = embeddedView ?? routedView
  if (view === 'board') return <TasksBoardPage />
  if (view === 'views') return <ViewsSection companyId={company.id} />
  return <TasksWorkPage embeddedView={embeddedView === 'registry' ? 'registry' : undefined} />
}

export default TasksWorkPage
