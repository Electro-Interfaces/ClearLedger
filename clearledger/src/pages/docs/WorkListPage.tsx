/**
 * Вся работа компании: документы и поручения одной лентой (этапы 13б и 13в).
 *
 * Экран отвечает на вопрос «что у нас в работе», а не «что у нас в документах и
 * отдельно в поручениях». Род предмета — колонка строки и фильтр, а не отдельный
 * раздел: «входящие» это отбор по виду, а не своя ветка кода.
 *
 * Строка запроса та же, что в реестре поручений: разбирает сервер, неузнанное
 * показывается человеку. Отбор формой и отбор строкой дают один результат,
 * потому что за ними одна ручка.
 */
import { useMemo, useState } from 'react'
import {
  keepPreviousData, useMutation, useQuery, useQueryClient,
} from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  BookmarkPlus, FileText, ListChecks, Loader2, RefreshCw, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { WorkItem } from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { QueryBar, type QuerySuggestions } from '@/components/tasks/QueryBar'
import { dt, PRIORITY_TONE, priorityWord } from '@/components/tasks/taskWords'
import { cn } from '@/lib/utils'

const PAGE = 50

const SCOPES: { key: string; label: string; hint: string }[] = [
  { key: 'open', label: 'В работе', hint: 'всё живое компании' },
  { key: 'mine', label: 'На мне', hint: 'я исполнитель или ответственный' },
  { key: 'assigned', label: 'Я поручил', hint: 'делает другой' },
  { key: 'done', label: 'Завершённое', hint: 'закрытое и исполненное' },
  { key: 'all', label: 'Всё', hint: 'без разреза по состоянию' },
]

export function WorkListPage() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const set = (kv: Record<string, string | null>) => setParams((p) => {
    const next = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) next.set(k, v); else next.delete(k) }
    if (!('page' in kv)) next.delete('page')
    return next
  }, { replace: true })

  const scope = params.get('scope') ?? 'open'
  const kind = params.get('kind') ?? ''
  const state = params.get('state') ?? ''
  const queryText = params.get('query') ?? ''
  // Предмет приходит из карточки проекта или объекта: «покажи всю работу по
  // этой площадке». В язык запросов его не завести — значение само содержит
  // двоеточие, и разбор пар «поле: значение» развалил бы ссылку.
  const ref = params.get('ref') ?? ''
  const page = Math.max(0, Number(params.get('page')) || 0)

  const filters = {
    scope: scope as workService.WorkFilters['scope'],
    kind: (kind || undefined) as 'doc' | 'task' | undefined,
    state: state || undefined,
    query: queryText || undefined,
    ref: ref || undefined,
    limit: PAGE, offset: page * PAGE,
  }
  const listQ = useQuery({
    queryKey: ['work', company.id, filters],
    queryFn: () => workService.listWork(company.id, filters),
    placeholderData: keepPreviousData,
  })
  const summaryQ = useQuery({
    queryKey: ['work-summary', company.id],
    queryFn: () => workService.workSummary(company.id),
    staleTime: 60 * 1000,
  })
  // Подсказки строки запроса — из справочников, которые уже загружены другими
  // экранами продукта: второй источник имён разошёлся бы с первым.
  const peopleQ = useQuery({
    queryKey: ['task-people', company.id],
    queryFn: () => tasksService.listTaskPeople(company.id),
    staleTime: 5 * 60 * 1000,
  })
  const typesQ = useQuery({
    queryKey: ['task-types', company.id],
    queryFn: () => tasksService.listTaskTypes(company.id),
    staleTime: 5 * 60 * 1000,
  })
  const projectsQ = useQuery({
    queryKey: ['task-projects', company.id, false],
    queryFn: () => tasksService.listTaskProjects(company.id),
    staleTime: 5 * 60 * 1000,
  })

  const suggestions: QuerySuggestions = useMemo(() => ({
    исполнитель: (peopleQ.data?.people ?? []).map((p) => p.name.split(' ')[0]),
    автор: (peopleQ.data?.people ?? []).map((p) => p.name.split(' ')[0]),
    тип: (typesQ.data?.types ?? []).map((t) => t.name),
    проект: (projectsQ.data?.projects ?? []).map((p) => p.code),
  }), [peopleQ.data, typesQ.data, projectsQ.data])

  const items = listQ.data?.work ?? []
  const total = listQ.data?.total ?? 0
  // Сводка знает счётчики, лента — только имена колонок: берём что есть.
  const columns: (workService.WorkColumn & {
    docs?: number; tasks?: number; total?: number
  })[] = summaryQ.data?.columns ?? listQ.data?.columns ?? []
  const hasFilter = !!(kind || state || queryText)

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Вся работа</h1>
          <p className="mt-0.5 max-w-2xl text-xs text-muted-foreground">
            Документы и поручения одной лентой. Род предмета — колонка и фильтр, а
            не отдельный раздел: «входящие» это отбор по виду документа.
          </p>
        </div>
        <Button variant="outline" size="sm" className="h-8"
          onClick={() => void listQ.refetch()} disabled={listQ.isFetching}>
          <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', listQ.isFetching && 'animate-spin')} />
          Обновить
        </Button>
      </div>

      <QueryBar className="max-w-3xl" value={queryText} suggestions={suggestions}
        result={listQ.data?.query} onChange={(v) => set({ query: v || null })} />

      {/* Сохранённые отборы — здесь, а не в рельсе слева: рельса это карта
          продукта, и она не должна расти от чужих отборов (этап 13ж). */}
      <SavedViews companyId={company.id} current={{ scope, kind, state, query: queryText }}
        onApply={(q) => set({
          scope: q.scope ?? null, kind: q.kind ?? null,
          state: q.state ?? null, query: q.query ?? null,
        })} />

      {/* Отбор по предмету пришёл ссылкой, и его не видно среди кнопок разреза.
          Без явной пометки человек читает короткий список как «работы нет», а
          снять сужение ему нечем. */}
      {ref && (
        <div className="flex items-center gap-2 rounded-md bg-muted/30 px-2.5 py-1.5 text-xs">
          <span className="text-muted-foreground">Только по предмету</span>
          <code className="rounded bg-background px-1.5 py-0.5 text-xs">{ref}</code>
          <Button size="sm" variant="ghost" className="ml-auto h-7 text-xs"
            onClick={() => set({ ref: null })}>
            Показать всю работу
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {SCOPES.map((s) => (
          <Button key={s.key} size="sm" title={s.hint}
            variant={scope === s.key ? 'default' : 'ghost'} className="h-8 text-xs"
            onClick={() => set({ scope: s.key === 'open' ? null : s.key })}>
            {s.label}
          </Button>
        ))}
        <span className="mx-1 h-5 w-px bg-border" />
        <Select value={kind || 'all'}
          onValueChange={(v) => set({ kind: v === 'all' ? null : v })}>
          <SelectTrigger className="h-8 w-[150px] text-xs">
            <SelectValue placeholder="Род" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Всё вместе</SelectItem>
            <SelectItem value="doc">Документы</SelectItem>
            <SelectItem value="task">Поручения</SelectItem>
          </SelectContent>
        </Select>
        <Select value={state || 'all'}
          onValueChange={(v) => set({ state: v === 'all' ? null : v })}>
          <SelectTrigger className="h-8 w-[180px] text-xs">
            <SelectValue placeholder="Состояние" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Любое состояние</SelectItem>
            {columns.map((c) => (
              <SelectItem key={c.code} value={c.code}>{c.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {hasFilter && (
          <Button variant="ghost" size="sm" className="h-8 text-muted-foreground"
            onClick={() => set({ kind: null, state: null, query: null })}>
            <X className="mr-1 h-3.5 w-3.5" />Сбросить
          </Button>
        )}
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {total} в отборе
        </span>
      </div>

      {/* Счётчики колонок — та же ось, что на доске: человек видит, где стоит
          работа, ещё до того, как открыл доску. */}
      {columns.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {columns.map((c) => (
            <button key={c.code} type="button"
              onClick={() => set({ state: state === c.code ? null : c.code })}
              className={cn('rounded-lg border px-2.5 py-1.5 text-left transition-colors',
                state === c.code ? 'border-primary bg-primary/5' : 'hover:bg-muted/50')}>
              <div className="text-xs text-muted-foreground">{c.name}</div>
              <div className="text-sm font-semibold tabular-nums">
                {c.total ?? 0}
                {c.docs !== undefined && (
                  <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                    {c.docs} док · {c.tasks} пор
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {listQ.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Собираем работу…
        </div>
      ) : listQ.isError ? (
        <QueryError message="Не удалось загрузить работу" onRetry={() => void listQ.refetch()} />
      ) : items.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          {hasFilter
            ? 'По этому отбору ничего нет. Проверьте строку запроса — неузнанное показано под ней.'
            : 'Работы пока нет. Заведите документ или поставьте поручение.'}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="w-[110px] px-3 py-2 text-left font-medium">Номер</th>
                <th className="px-3 py-2 text-left font-medium">Предмет</th>
                <th className="w-[150px] px-3 py-2 text-left font-medium">Состояние</th>
                <th className="w-[150px] px-3 py-2 text-left font-medium">Ответственный</th>
                <th className="w-[110px] px-3 py-2 text-left font-medium">Срок</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Row key={`${item.kind}-${item.id}`} item={item}
                  onOpen={() => navigate(workService.workHref(item))} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Страница {page + 1} из {Math.ceil(total / PAGE)}</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" className="h-7" disabled={page === 0}
              onClick={() => set({ page: String(page) })}>Назад</Button>
            <Button size="sm" variant="outline" className="h-7"
              disabled={(page + 1) * PAGE >= total}
              onClick={() => set({ page: String(page + 2) })}>Вперёд</Button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Сохранённые отборы общей ленты: применить одним нажатием и завести новый. */
function SavedViews({ companyId, current, onApply }: {
  companyId: string
  current: Record<string, string>
  onApply: (query: Record<string, string>) => void
}) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [adding, setAdding] = useState(false)

  const q = useQuery({
    queryKey: ['task-views', companyId, 'work'],
    queryFn: () => tasksService.listTaskViews(companyId, 'work'),
    staleTime: 60 * 1000,
  })
  const save = useMutation({
    mutationFn: () => tasksService.createTaskView({
      companyId, name: name.trim(), listScope: 'work',
      query: Object.fromEntries(Object.entries(current).filter(([, v]) => v)),
    }),
    onSuccess: () => {
      toast.success('Отбор сохранён')
      setAdding(false); setName('')
      void qc.invalidateQueries({ queryKey: ['task-views'] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const drop = useMutation({
    mutationFn: (id: string) => tasksService.deleteTaskView(id, companyId),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['task-views'] }) },
    onError: (e) => toast.error((e as Error).message),
  })

  const views = q.data?.views ?? []
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {views.map((v) => (
        <span key={v.id}
          className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">
          <button type="button" onClick={() => onApply(v.query as Record<string, string>)}>
            {v.name}
          </button>
          {v.can_delete !== false && (
            <button type="button" aria-label={`Удалить отбор ${v.name}`}
              className="text-muted-foreground hover:text-foreground"
              onClick={() => drop.mutate(v.id)}>×</button>
          )}
        </span>
      ))}
      {adding ? (
        <span className="inline-flex items-center gap-1">
          <Input value={name} autoFocus maxLength={120} placeholder="Название отбора"
            className="h-7 w-[180px] text-xs"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) save.mutate() }} />
          <Button size="sm" className="h-7 text-xs" disabled={!name.trim() || save.isPending}
            onClick={() => save.mutate()}>Сохранить</Button>
          <Button size="sm" variant="ghost" className="h-7 px-2"
            onClick={() => setAdding(false)}><X className="h-3.5 w-3.5" /></Button>
        </span>
      ) : (
        <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground"
          onClick={() => setAdding(true)}>
          <BookmarkPlus className="mr-1 h-3.5 w-3.5" />Сохранить отбор
        </Button>
      )}
    </div>
  )
}

function Row({ item, onOpen }: { item: WorkItem; onOpen: () => void }) {
  const Icon = item.kind === 'doc' ? FileText : ListChecks
  return (
    <tr className="cursor-pointer border-t hover:bg-muted/40" onClick={onOpen}>
      <td className="px-3 py-2">
        <span className="inline-flex items-center gap-1.5">
          {/* Род — значок, а не раздел: человеку важно, что перед ним, но не
              настолько, чтобы уводить это в отдельный список. */}
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
            aria-label={item.kind === 'doc' ? 'документ' : 'поручение'} />
          <span className="font-mono text-xs">{item.key}</span>
        </span>
      </td>
      <td className="px-3 py-2">
        {/* Заголовок основным цветом. Приоритет ушёл в мету словом: красный
            заголовок стоял рядом с красным сроком, и два красных на строке
            означали разное — «важно» и «просрочено». */}
        <div className="font-medium leading-snug">{item.title}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          {item.priority && priorityWord(item.priority) && (
            <span className={PRIORITY_TONE[item.priority]}>
              {priorityWord(item.priority)}
            </span>
          )}
          {item.type && <span>{item.type}</span>}
          {item.project && <span className="font-mono">{item.project}</span>}
          {item.object && <span>{item.object}</span>}
          {item.labels.map((l) => (
            <span key={l.id} className="rounded border border-border/60 px-1">{l.name}</span>
          ))}
        </div>
      </td>
      <td className="px-3 py-2">
        <Badge variant="outline" className="h-5 px-1.5 text-xs">{item.state_name}</Badge>
        {/* Этап — только когда говорит новое: у поручений он часто зовётся так
            же, как состояние, и «В работе» под «В работе» читалось опечаткой. */}
        {item.stage && item.stage !== item.state_name && (
          <div className="mt-0.5 text-xs text-muted-foreground">{item.stage}</div>
        )}
      </td>
      <td className="px-3 py-2 text-xs">{item.responsible ?? '—'}</td>
      <td className={cn('px-3 py-2 text-xs tabular-nums',
        item.overdue && 'text-red-600 dark:text-red-400')}>
        {item.due_at ? dt(item.due_at) : '—'}
      </td>
    </tr>
  )
}

export default WorkListPage
