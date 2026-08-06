/**
 * Приложение «Задачи» — работа компании (docs/TASKS.md ecosystem-deploy).
 *
 * Два раздела: «Работа» (список и постановка) и «Типы» (маршруты — чем один вид
 * работы отличается от другого). Движок свой, в Ядре; заявки Поддержки живут
 * отдельно и сюда не переезжают.
 */
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight, BarChart3, CheckCircle2, ListChecks, Loader2, Plus, RefreshCw, Route,
  Trash2, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import type { RouteStage, TaskScope, TaskType } from '@/services/tasksService'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import { TasksOverviewSection } from '@/components/tasks/TasksOverviewSection'

const nf = new Intl.NumberFormat('ru-RU')
const dt = (s: string | null) => (s ? new Date(s).toLocaleDateString('ru-RU') : '—')
const dtT = (s: string | null) => (s ? new Date(s).toLocaleString('ru-RU',
  { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—')

// Словарь общий с «Заявками»: одна и та же срочность не должна называться
// по-разному в двух продуктах одного пространства.
const PRIORITY_LABEL: Record<string, string> = {
  low: 'низкая', medium: 'обычная', high: 'срочная', critical: 'критичная',
}
const PRIORITY_TONE: Record<string, string> = {
  critical: 'text-red-600 dark:text-red-400',
  high: 'text-amber-600 dark:text-amber-400',
}
const STATUS_LABEL: Record<string, string> = {
  open: 'в работе', done: 'выполнена', cancelled: 'отменена',
}

type Section = 'overview' | 'work' | 'types'

export function TasksAppPage() {
  const { company } = useCompany()
  // Раздел, период и фильтры живут в адресе, а не в состоянии: на экран «просрочки
  // у Петрова» можно дать ссылку, а обзор проваливается в список сменой параметров.
  const [params, setParams] = useSearchParams()
  const section = (params.get('view') ?? 'overview') as Section
  const days = Number(params.get('days')) || 30
  const patch = (kv: Record<string, string | undefined>) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) n.set(k, v); else n.delete(k) }
    return n
  }, { replace: true })

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Задачи</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Работа компании: поручения, согласования, регламент. Тип задаёт маршрут —
            задача идёт по стадиям и в любой момент может уйти другому исполнителю.
          </p>
        </div>
        <Tabs value={section} onValueChange={(v) => patch({ view: v })}>
          <TabsList variant="line" className="h-9">
            <TabsTrigger value="overview"><BarChart3 className="mr-1.5 h-3.5 w-3.5" />Обзор</TabsTrigger>
            <TabsTrigger value="work"><ListChecks className="mr-1.5 h-3.5 w-3.5" />Работа</TabsTrigger>
            <TabsTrigger value="types"><Route className="mr-1.5 h-3.5 w-3.5" />Типы</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {section === 'overview' ? (
        <TasksOverviewSection companyId={company.id} days={days}
          onDays={(d) => patch({ days: String(d) })}
          onDrill={(f) => patch({
            view: 'work', scope: f.scope, assignee: f.assignee,
            type: f.type, object: f.object, task: undefined,
          })} />
      ) : section === 'types' ? <TypesSection companyId={company.id} />
        : <WorkSection companyId={company.id} />}
    </div>
  )
}

/* ── Раздел «Работа» ─────────────────────────────────────────────────── */

function WorkSection({ companyId }: { companyId: string }) {
  // Весь отбор — в адресе: карточка объекта ссылается на /tasks?object=<id>, обзор
  // проваливается сюда с ?assignee=/?scope=, а открытая карточка (?task=<id>)
  // приходит из быстрой панели в шапке. Одно состояние, на которое можно сослаться.
  const [params, setParams] = useSearchParams()
  const set = (k: string, v: string | null) => setParams((p) => {
    const n = new URLSearchParams(p)
    if (v) n.set(k, v); else n.delete(k)
    return n
  }, { replace: true })
  const scope = (params.get('scope') ?? 'open') as TaskScope
  const objectId = params.get('object') ?? ''
  const typeId = params.get('type') ?? ''
  const assigneeId = params.get('assignee') ?? ''
  const openId = params.get('task')
  const setOpenId = (v: string | null) => set('task', v)

  const objectsQ = useQuery({
    queryKey: ['space-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const typesQ = useQuery({
    queryKey: ['task-types', companyId],
    queryFn: () => tasksService.listTaskTypes(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  // Порядок ключа: scope · объект · тип · исполнитель. Тот же ключ у быстрой панели
  // в шапке и у счётчика просрочек — иначе они грузили бы те же строки второй раз.
  const q = useQuery({
    queryKey: ['tasks', companyId, scope, objectId, typeId, assigneeId],
    queryFn: () => tasksService.listTasks(companyId, scope, {
      objectId: objectId || undefined, typeId: typeId || undefined,
      assigneeId: assigneeId || undefined,
    }),
    placeholderData: keepPreviousData,
  })
  const tasks = q.data?.tasks ?? []

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={scope} onValueChange={(v) => set('scope', v)}>
          <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="open">Активные</SelectItem>
            <SelectItem value="mine">Мои</SelectItem>
            <SelectItem value="overdue">Просроченные</SelectItem>
            <SelectItem value="closed">Завершённые</SelectItem>
            <SelectItem value="all">Все</SelectItem>
          </SelectContent>
        </Select>
        <Select value={assigneeId || 'all'} onValueChange={(v) => set('assignee', v === 'all' ? null : v)}>
          <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue placeholder="Исполнитель" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Любой исполнитель</SelectItem>
            {(peopleQ.data?.people ?? []).map((p) => (
              <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={typeId || 'all'} onValueChange={(v) => set('type', v === 'all' ? null : v)}>
          <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue placeholder="Тип" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все типы</SelectItem>
            {(typesQ.data?.types ?? []).map((t) => (
              <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={objectId || 'all'} onValueChange={(v) => set('object', v === 'all' ? null : v)}>
          <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue placeholder="Объект" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все объекты</SelectItem>
            {(objectsQ.data ?? []).map((o) => (
              <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-[11px] text-muted-foreground">задач: {nf.format(tasks.length)}</span>
        <span className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', q.isFetching && 'animate-spin')} />Обновить
          </Button>
          <CreateTaskDialog companyId={companyId} types={typesQ.data?.types ?? []}
            onCreated={() => q.refetch()} />
        </span>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка задач…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить задачи" onRetry={() => void q.refetch()} />
      ) : tasks.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          {scope === 'open'
            ? 'Активных задач нет. Поставьте первую — кнопка «Поставить задачу».'
            : 'Под этот фильтр задач нет.'}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[960px] text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <Th>№</Th><Th>Задача</Th><Th>Тип</Th><Th>Стадия</Th>
                <Th>Исполнитель</Th><Th>Объект</Th><Th>Срок</Th><Th>Обновлена</Th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id} tabIndex={0} aria-haspopup="dialog"
                  onClick={() => setOpenId(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpenId(t.id) }
                  }}
                  className="cursor-pointer border-t transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                  <Td className="whitespace-nowrap font-medium">№{t.number}</Td>
                  <Td>
                    <div className="font-medium text-foreground">{t.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                      <span>{STATUS_LABEL[t.status] ?? t.status}</span>
                      {(t.priority === 'high' || t.priority === 'critical') && (
                        <span className={PRIORITY_TONE[t.priority]}>{PRIORITY_LABEL[t.priority]}</span>
                      )}
                      <span>· автор {t.author ?? '—'}</span>
                    </div>
                  </Td>
                  <Td>{t.type ?? <span className="text-muted-foreground">поручение</span>}</Td>
                  <Td>
                    {t.status === 'open' && t.stage
                      ? <span className="whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px]">{t.stage}</span>
                      : <span className="text-muted-foreground">—</span>}
                  </Td>
                  <Td>{t.assignee ?? <span className="text-muted-foreground">не назначен</span>}</Td>
                  <Td>{t.object ?? '—'}</Td>
                  <Td className={cn('whitespace-nowrap', t.overdue && 'font-medium text-red-600 dark:text-red-400')}>
                    {t.overdue ? `просрочена · ${dt(t.due_at)}` : dt(t.due_at)}
                  </Td>
                  <Td className="whitespace-nowrap text-muted-foreground">{dtT(t.updated_at)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">
        Строка открывает карточку: там маршрут, переадресация и след — кто что сделал.
      </p>

      <Sheet open={!!openId} onOpenChange={(v) => { if (!v) setOpenId(null) }}>
        <SheetContent side="right" className="w-full p-0 sm:max-w-lg">
          <SheetTitle className="sr-only">Карточка задачи</SheetTitle>
          <SheetDescription className="sr-only">Маршрут, исполнитель и след</SheetDescription>
          {openId && (
            <TaskCard id={openId} companyId={companyId}
              onChanged={() => q.refetch()} />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

/** Карточка задачи: маршрут, переадресация, завершение и след. */
function TaskCard({ id, companyId, onChanged }: {
  id: string; companyId: string; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const q = useQuery({
    queryKey: ['task', id, companyId],
    queryFn: () => tasksService.taskDetails(id, companyId),
  })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const act = useMutation({
    mutationFn: (data: Parameters<typeof tasksService.taskAction>[1]) =>
      tasksService.taskAction(id, data),
    onSuccess: () => {
      setNote('')
      qc.invalidateQueries({ queryKey: ['task', id] })
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const t = q.data

  if (q.isLoading) {
    return <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Загрузка задачи…</div>
  }
  if (!t) return <div className="p-6 text-sm text-destructive">Не удалось загрузить задачу</div>

  const stageIndex = t.route.findIndex((s) => s.code === t.stage_code)
  const next = stageIndex >= 0 ? t.route[stageIndex + 1] : t.route[0]

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="text-base font-semibold">№{t.number}</span>
          {t.type && <Badge variant="outline" className="h-5 px-1.5 text-[11px]">{t.type}</Badge>}
          <span className="text-[11px] text-muted-foreground">{STATUS_LABEL[t.status] ?? t.status}</span>
        </div>
        <div className="mt-1 text-sm">{t.title}</div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4 text-sm">
        {/* Маршрут: где задача сейчас и что дальше. Полоса, а не выпадающий
            список — человек должен видеть весь путь, а не только текущий шаг. */}
        <div>
          <div className="mb-1.5 text-xs text-muted-foreground">Маршрут</div>
          <div className="flex flex-wrap items-center gap-1">
            {t.route.map((s, i) => (
              <span key={s.code} className="flex items-center gap-1">
                {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                <button type="button" disabled={t.status !== 'open' || act.isPending}
                  onClick={() => act.mutate({ companyId, stageCode: s.code, note: note || undefined })}
                  className={cn('rounded-md border px-2 py-0.5 text-[11px] transition-colors',
                    s.code === t.stage_code
                      ? 'border-primary bg-primary/10 font-medium text-foreground'
                      : 'text-muted-foreground hover:bg-muted/60',
                    t.status !== 'open' && 'cursor-default opacity-60')}>
                  {s.name}
                </button>
              </span>
            ))}
          </div>
        </div>

        {t.status === 'open' && (
          <div className="flex flex-wrap items-center gap-2">
            {next && (
              <Button size="sm" className="h-8" disabled={act.isPending}
                onClick={() => act.mutate({ companyId, stageCode: next.code, note: note || undefined })}>
                <ArrowRight className="mr-1.5 h-3.5 w-3.5" />Дальше: {next.name}
              </Button>
            )}
            <Button size="sm" variant="outline" className="h-8" disabled={act.isPending}
              onClick={() => act.mutate({ companyId, status: 'done', note: note || undefined })}>
              <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />Выполнена
            </Button>
            <Button size="sm" variant="ghost" className="h-8 text-muted-foreground"
              disabled={act.isPending}
              onClick={() => act.mutate({ companyId, status: 'cancelled', note: note || undefined })}>
              <X className="mr-1.5 h-3.5 w-3.5" />Отменить
            </Button>
          </div>
        )}

        {t.status === 'open' && (
          <div className="space-y-1.5">
            <Label className="text-xs">Исполнитель</Label>
            <Select value={t.assignee_id ?? 'none'}
              onValueChange={(v) => act.mutate({
                companyId, assigneeId: v === 'none' ? null : v, note: note || undefined,
              })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Не назначен" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Не назначен</SelectItem>
                {(peopleQ.data?.people ?? []).map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">
              Смена исполнителя — это переадресация: она попадёт в след с вашим именем.
            </p>
          </div>
        )}

        {t.description && (
          <p className="whitespace-pre-wrap text-sm text-foreground/90">{t.description}</p>
        )}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <Fact label="Срочность" value={PRIORITY_LABEL[t.priority] ?? t.priority}
            tone={PRIORITY_TONE[t.priority]} />
          <Fact label="Срок" value={t.overdue ? `просрочена · ${dt(t.due_at)}` : dt(t.due_at)}
            tone={t.overdue ? 'text-red-600 dark:text-red-400' : undefined} />
          <Fact label="Объект" value={t.object ?? '—'} />
          <Fact label="Автор" value={t.author ?? '—'} />
          <Fact label="Поставлена" value={dtT(t.created_at)} />
          <Fact label="Обновлена" value={dtT(t.updated_at)} />
        </dl>

        {/* След: почему работа стоит. Без него переадресация выглядит как
            самопроизвольная смена исполнителя. */}
        <div>
          <div className="mb-1.5 text-xs text-muted-foreground">След задачи</div>
          <div className="space-y-2">
            {t.events.map((e) => (
              <div key={e.id} className="rounded-md border border-border/70 bg-card/60 px-3 py-1.5 text-xs">
                <div className="flex flex-wrap items-baseline gap-1.5">
                  <span className="font-medium">{e.user ?? 'система'}</span>
                  <span className="text-muted-foreground">{eventText(e)}</span>
                  <span className="ml-auto text-[11px] text-muted-foreground">{dtT(e.created_at)}</span>
                </div>
                {e.note && <div className="mt-0.5 whitespace-pre-wrap text-foreground/90">{e.note}</div>}
              </div>
            ))}
          </div>
        </div>
      </div>

      {t.status === 'open' && (
        <div className="border-t px-5 py-3">
          <div className="flex items-end gap-2">
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
              maxLength={2000} className="text-sm"
              placeholder="Написать в след: что сделано, что мешает. Уйдёт вместе с действием." />
            <Button size="sm" className="h-8" disabled={!note.trim() || act.isPending}
              onClick={() => act.mutate({ companyId, note: note.trim() })}>Записать</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function eventText(e: { kind: string; from: string | null; to: string | null }): string {
  switch (e.kind) {
    case 'created': return `поставил задачу · ${e.to ?? ''}`
    case 'stage': return `стадия: ${e.from ?? '—'} → ${e.to ?? '—'}`
    case 'assign': return e.to ? `исполнитель: ${e.from ?? '—'} → ${e.to}` : 'снял исполнителя'
    case 'status': return `статус: ${STATUS_LABEL[e.from ?? ''] ?? e.from} → ${STATUS_LABEL[e.to ?? ''] ?? e.to}`
    default: return 'написал'
  }
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('mt-0.5 text-foreground', tone)}>{value}</dd>
    </div>
  )
}

function CreateTaskDialog({ companyId, types, onCreated }: {
  companyId: string; types: TaskType[]; onCreated: () => void
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [typeId, setTypeId] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [objectId, setObjectId] = useState('')
  const [priority, setPriority] = useState('')
  const [dueAt, setDueAt] = useState('')

  const objectsQ = useQuery({
    queryKey: ['space-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    enabled: open, staleTime: 5 * 60 * 1000,
  })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: open, staleTime: 5 * 60 * 1000,
  })
  const type = types.find((t) => t.id === typeId)

  const reset = () => {
    setTitle(''); setDescription(''); setTypeId(''); setAssigneeId('')
    setObjectId(''); setPriority(''); setDueAt('')
  }
  const create = useMutation({
    mutationFn: () => tasksService.createTask({
      companyId, title: title.trim(), description: description.trim() || undefined,
      typeId: typeId || undefined, assigneeId: assigneeId || undefined,
      objectId: objectId || undefined, priority: priority || undefined,
      // Срок вводят датой — на сервер уходит начало суток в поясе браузера.
      dueAt: dueAt ? new Date(`${dueAt}T00:00`).toISOString() : undefined,
    }),
    onSuccess: () => {
      toast.success('Задача поставлена')
      qc.invalidateQueries({ queryKey: ['tasks'] })
      setOpen(false); reset(); onCreated()
    },
    onError: (e) => toast.error(`Не удалось поставить задачу: ${(e as Error).message}`),
  })

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset() }}>
      <DialogTrigger asChild>
        <Button size="sm" className="h-8"><Plus className="mr-1.5 h-3.5 w-3.5" />Поставить задачу</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Новая задача</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Что сделать</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="Коротко: что нужно сделать" maxLength={300} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Тип</Label>
              <Select value={typeId || 'none'} onValueChange={(v) => setTypeId(v === 'none' ? '' : v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Поручение (без типа)</SelectItem>
                  {types.filter((t) => t.is_active).map((t) => (
                    <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {type && (
                <p className="text-[11px] text-muted-foreground">
                  Маршрут: {type.route.map((s) => s.name).join(' → ')}
                  {type.due_days != null && ` · срок ${type.due_days} дн.`}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label>Исполнитель</Label>
              <Select value={assigneeId || 'none'} onValueChange={(v) => setAssigneeId(v === 'none' ? '' : v)}>
                <SelectTrigger><SelectValue placeholder={
                  peopleQ.isLoading ? 'Загрузка…' : 'Не назначен'} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Не назначен</SelectItem>
                  {(peopleQ.data?.people ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Описание</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="Подробности: что именно, где, к какому результату." rows={3} maxLength={8000} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label>Объект</Label>
              <Select value={objectId || 'none'} onValueChange={(v) => setObjectId(v === 'none' ? '' : v)}>
                <SelectTrigger><SelectValue placeholder="Без объекта" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Без объекта</SelectItem>
                  {(objectsQ.data ?? []).filter((o) => o.status !== 'closed').map((o) => (
                    <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Срочность</Label>
              <Select value={priority || 'default'}
                onValueChange={(v) => setPriority(v === 'default' ? '' : v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">
                    {type ? `Как у типа (${PRIORITY_LABEL[type.default_priority]})` : 'Обычная'}
                  </SelectItem>
                  <SelectItem value="low">Низкая</SelectItem>
                  <SelectItem value="medium">Обычная</SelectItem>
                  <SelectItem value="high">Срочная</SelectItem>
                  <SelectItem value="critical">Критичная</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Срок</Label>
              <Input type="date" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button disabled={title.trim().length < 3 || create.isPending}
            onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Поставить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── Раздел «Типы»: маршруты ─────────────────────────────────────────── */

function TypesSection({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['task-types', companyId],
    queryFn: () => tasksService.listTaskTypes(companyId),
  })
  const [edit, setEdit] = useState<TaskType | 'new' | null>(null)
  const starter = useMutation({
    mutationFn: () => tasksService.createStarterTypes(companyId),
    onSuccess: (r) => {
      toast.success(r.added ? `Заведено типов: ${r.added}` : 'Все заготовки уже есть')
      qc.invalidateQueries({ queryKey: ['task-types'] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const types = q.data?.types ?? []

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-muted-foreground">
          Тип — это правило: какой маршрут проходит работа, с какой срочностью и к какому сроку.
        </span>
        <span className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8" disabled={starter.isPending}
            onClick={() => starter.mutate()}>Завести заготовки</Button>
          <Button size="sm" className="h-8" onClick={() => setEdit('new')}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />Новый тип
          </Button>
        </span>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка типов…
        </div>
      ) : types.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Типов пока нет — задачи идут маршрутом поручения:{' '}
          {(q.data?.default_route ?? []).map((s) => s.name).join(' → ')}.
          Нажмите «Завести заготовки», чтобы получить поручение, согласование и инцидент.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[820px] text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr><Th>Тип</Th><Th>Маршрут</Th><Th>Срочность</Th><Th>Срок</Th><Th>Состояние</Th></tr>
            </thead>
            <tbody>
              {types.map((t) => (
                <tr key={t.id} tabIndex={0} onClick={() => setEdit(t)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); setEdit(t) } }}
                  className={cn('cursor-pointer border-t hover:bg-muted/40', !t.is_active && 'opacity-50')}>
                  <Td>
                    <div className="font-medium text-foreground">{t.name}</div>
                    {t.description && <div className="mt-0.5 text-[11px] text-muted-foreground">{t.description}</div>}
                  </Td>
                  <Td>{t.route.map((s) => s.name).join(' → ')}</Td>
                  <Td>{PRIORITY_LABEL[t.default_priority] ?? t.default_priority}</Td>
                  <Td>{t.due_days != null ? `${t.due_days} дн.` : '—'}</Td>
                  <Td>{t.is_active ? 'действует' : 'выключен'}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Sheet open={!!edit} onOpenChange={(v) => { if (!v) setEdit(null) }}>
        <SheetContent side="right" className="w-full p-0 sm:max-w-lg">
          <SheetTitle className="sr-only">Тип задачи</SheetTitle>
          <SheetDescription className="sr-only">Маршрут, срочность и срок</SheetDescription>
          {edit && (
            <TypeEditor companyId={companyId} type={edit === 'new' ? null : edit}
              onSaved={() => {
                qc.invalidateQueries({ queryKey: ['task-types'] })
                setEdit(null)
              }} />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function TypeEditor({ companyId, type, onSaved }: {
  companyId: string; type: TaskType | null; onSaved: () => void
}) {
  const [code, setCode] = useState(type?.code ?? '')
  const [name, setName] = useState(type?.name ?? '')
  const [description, setDescription] = useState(type?.description ?? '')
  const [priority, setPriority] = useState(type?.default_priority ?? 'medium')
  const [dueDays, setDueDays] = useState(type?.due_days != null ? String(type.due_days) : '')
  const [isActive, setIsActive] = useState(type?.is_active ?? true)
  const [route, setRoute] = useState<RouteStage[]>(type?.route ?? [{ code: 'new', name: 'Постановка' }])

  const save = useMutation({
    mutationFn: () => tasksService.saveTaskType({
      companyId, id: type?.id, code: code.trim(), name: name.trim(),
      description: description.trim() || undefined, route,
      defaultPriority: priority, dueDays: dueDays === '' ? null : Number(dueDays),
      isActive, sortOrder: type?.sort_order ?? 100,
    }),
    onSuccess: () => { toast.success('Тип сохранён'); onSaved() },
    onError: (e) => toast.error((e as Error).message),
  })

  const setStage = (i: number, patch: Partial<RouteStage>) =>
    setRoute((r) => r.map((s, j) => (j === i ? { ...s, ...patch } : s)))

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-5 py-4 text-base font-semibold">
        {type ? type.name : 'Новый тип задачи'}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Название</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
          </div>
          <div className="space-y-1.5">
            <Label>Код</Label>
            <Input value={code} disabled={!!type} maxLength={40}
              onChange={(e) => setCode(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))}
              placeholder="approval" />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label>Пояснение</Label>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500}
            placeholder="Когда ставят задачу этого типа" />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <Label>Срочность</Label>
            <Select value={priority} onValueChange={setPriority}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(PRIORITY_LABEL).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Срок, дней</Label>
            <Input type="number" min={0} max={365} value={dueDays}
              onChange={(e) => setDueDays(e.target.value)} placeholder="без срока" />
          </div>
          <div className="space-y-1.5">
            <Label>Состояние</Label>
            <Select value={isActive ? 'on' : 'off'} onValueChange={(v) => setIsActive(v === 'on')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="on">Действует</SelectItem>
                <SelectItem value="off">Выключен</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>Маршрут</Label>
          <p className="text-[11px] text-muted-foreground">
            Стадии по порядку — так задача и пойдёт. Выключенные стадии не бывают:
            лишнюю проще удалить.
          </p>
          <div className="space-y-2">
            {route.map((s, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-4 text-center text-xs text-muted-foreground">{i + 1}</span>
                <Input className="h-8 flex-1 text-xs" value={s.name} placeholder="Название стадии"
                  onChange={(e) => setStage(i, { name: e.target.value })} />
                <Input className="h-8 w-32 text-xs" value={s.code} placeholder="код"
                  onChange={(e) => setStage(i, {
                    code: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''),
                  })} />
                <Button variant="ghost" size="sm" className="h-8 px-2"
                  onClick={() => setRoute((r) => r.filter((_, j) => j !== i))}
                  aria-label="Удалить стадию">
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
          <Button variant="outline" size="sm" className="h-8"
            onClick={() => setRoute((r) => [...r, { code: `stage${r.length + 1}`, name: '' }])}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />Стадия
          </Button>
        </div>
      </div>
      <div className="border-t px-5 py-3">
        <Button className="w-full" disabled={save.isPending
          || name.trim().length < 2 || code.trim().length < 2
          || route.filter((s) => s.code && s.name.trim()).length === 0}
          onClick={() => save.mutate()}>
          {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Сохранить
        </Button>
      </div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="p-2.5 text-left font-medium">{children}</th>
}
function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('p-2.5 align-top', className)}>{children}</td>
}

export default TasksAppPage
