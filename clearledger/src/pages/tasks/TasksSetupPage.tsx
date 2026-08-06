/**
 * Раздел «Настройка»: типы с маршрутами и метки компании.
 *
 * Тип — правило, по которому идёт работа, поэтому его правит администратор
 * пространства. Метка — рабочий ярлык, её заводит любой участник: поход к
 * администратору за ярлыком никто не сделает.
 */
import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import type { RouteStage, TaskType } from '@/services/tasksService'
import { listSpaceConnectors } from '@/services/spaceConnectorsService'
import { PRIORITY_LABEL } from '@/components/tasks/taskWords'
import { tasksRouteOf, useTasksView } from './TasksLayout'
import { RecurrencesSection, TemplatesSection } from './TasksRegulation'

export function TasksSetupPage() {
  const { company } = useCompany()
  const view = useTasksView(tasksRouteOf(useLocation().pathname))
  if (view === 'labels') return <LabelsSection companyId={company.id} />
  if (view === 'external') return <ExternalSection companyId={company.id} />
  if (view === 'templates') return <TemplatesSection companyId={company.id} />
  if (view === 'recurrences') return <RecurrencesSection companyId={company.id} />
  return <TypesSection companyId={company.id} />
}

/* ── Внешние подключения ─────────────────────────────────────────────── */

function ExternalSection({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['space-connectors', companyId],
    queryFn: () => listSpaceConnectors(companyId),
  })
  // Делегировать можно только туда, где живёт чужая работа: файловый канал Учёта
  // и платформенные сервисы — источники данных, а не внешние исполнители.
  const rows = (q.data?.connectors ?? []).filter(
    (c) => c.app !== 'ledger' && c.app !== 'core')

  return (
    <div className="space-y-3 p-4">
      <div>
        <h1 className="text-lg font-semibold">Внешние подключения</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Куда из задачи можно делегировать работу. Подключения заводит и настраивает
          приложение-владелец — здесь витрина: своего реестра коннекторов у «Задач» нет.
        </p>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Спрашиваем приложения…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось собрать подключения" onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          У компании нет живых подключений к внешним системам. Пока их не заведут в
          приложении-владельце, работу наружу отдают письмом — прямо из карточки задачи.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr><Th>Подключение</Th><Th>Владелец</Th><Th>Что приносит</Th>
                <Th>Состояние</Th><Th>Последняя сверка</Th></tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.key} className="border-t">
                  <Td>
                    <div className="font-medium text-foreground">{c.label}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">{c.kind}</div>
                  </Td>
                  <Td>{c.app_name}</Td>
                  <Td className="text-muted-foreground">{c.brings || '—'}</Td>
                  <Td>
                    <span className={cn('rounded border px-1.5 py-0.5 text-[11px]',
                      c.enabled
                        ? 'border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400'
                        : 'border-border text-muted-foreground')}>
                      {c.enabled ? 'работает' : 'выключено'}
                    </span>
                    {c.last_error && (
                      <div className="mt-0.5 text-[11px] text-red-600 dark:text-red-400">
                        {c.last_error}
                      </div>
                    )}
                  </Td>
                  <Td className="text-muted-foreground">
                    {c.last_sync_at ? new Date(c.last_sync_at).toLocaleString('ru-RU') : '—'}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(q.data?.problems ?? []).length > 0 && (
        // Приложение, которое не ответило, называем: список честнее молчания.
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs">
          <div className="font-medium">Не ответили</div>
          {q.data!.problems.map((p) => (
            <div key={p.app} className="mt-0.5 text-muted-foreground">
              {p.app_name}: {p.error}
            </div>
          ))}
        </div>
      )}

      <p className="text-[11px] text-muted-foreground">
        Работу в чужой системе заводит её владелец. В карточке задачи остаётся связь с
        ней — номер, ссылка и состояние; вторую правду о чужой работе мы не держим.
        Автосоздание работы появится, когда приложение-владелец отдаст для этого ручку.
      </p>
    </div>
  )
}

/* ── Типы и маршруты ─────────────────────────────────────────────────── */

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
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Типы и маршруты</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Тип — это правило: каким маршрутом идёт работа, с какой срочностью и к
            какому сроку.
          </p>
        </div>
        <span className="flex items-center gap-2">
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
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить типы" onRetry={() => void q.refetch()} />
      ) : types.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          <p>
            Типов пока нет — задачи идут маршрутом поручения:{' '}
            {(q.data?.default_route ?? []).map((s) => s.name).join(' → ')}.
          </p>
          <Button size="sm" className="mt-3" disabled={starter.isPending}
            onClick={() => starter.mutate()}>
            Завести заготовки: поручение, согласование, инцидент
          </Button>
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
                    {t.description && (
                      <div className="mt-0.5 text-[11px] text-muted-foreground">{t.description}</div>
                    )}
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
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const [code, setCode] = useState(type?.code ?? '')
  const [name, setName] = useState(type?.name ?? '')
  const [description, setDescription] = useState(type?.description ?? '')
  const [priority, setPriority] = useState(type?.default_priority ?? 'medium')
  const [dueDays, setDueDays] = useState(type?.due_days != null ? String(type.due_days) : '')
  const [isActive, setIsActive] = useState(type?.is_active ?? true)
  const [reactionHours, setReactionHours] = useState(
    type?.reaction_hours != null ? String(type.reaction_hours) : '')
  const [escalateToId, setEscalateToId] = useState(type?.escalate_to_id ?? '')
  const [route, setRoute] = useState<RouteStage[]>(
    type?.route ?? [{ code: 'new', name: 'Постановка' }])

  const save = useMutation({
    mutationFn: () => tasksService.saveTaskType({
      companyId, id: type?.id, code: code.trim(), name: name.trim(),
      description: description.trim() || undefined, route,
      defaultPriority: priority, dueDays: dueDays === '' ? null : Number(dueDays),
      isActive, sortOrder: type?.sort_order ?? 100,
      reactionHours: reactionHours === '' ? null : Number(reactionHours),
      escalateToId: escalateToId || null,
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
          <Input value={description} onChange={(e) => setDescription(e.target.value)}
            maxLength={500} placeholder="Когда ставят задачу этого типа" />
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

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Время реакции, часов</Label>
            <Input type="number" min={1} max={720} value={reactionHours}
              onChange={(e) => setReactionHours(e.target.value)} placeholder="не следим" />
            <p className="text-[11px] text-muted-foreground">
              Сколько даётся на первый отклик исполнителя. Не откликнулся — уйдёт
              эскалация, и в ленте останется след.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Кому эскалировать</Label>
            <Select value={escalateToId || 'author'}
              onValueChange={(v) => setEscalateToId(v === 'author' ? '' : v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="author">Автору задачи</SelectItem>
                {(peopleQ.data?.people ?? []).map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>Маршрут</Label>
          <p className="text-[11px] text-muted-foreground">
            Стадии по порядку — так задача и пойдёт. Выключенных стадий не бывает:
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

/* ── Метки ───────────────────────────────────────────────────────────── */

// Тона из альфа-шкалы: один класс работает в обеих темах, произвольный hex — нет.
const COLORS: { key: string; label: string; cls: string }[] = [
  { key: 'slate', label: 'серая', cls: 'border-slate-500/40 bg-slate-500/10' },
  { key: 'amber', label: 'жёлтая', cls: 'border-amber-500/40 bg-amber-500/10' },
  { key: 'sky', label: 'синяя', cls: 'border-sky-500/40 bg-sky-500/10' },
  { key: 'emerald', label: 'зелёная', cls: 'border-emerald-500/40 bg-emerald-500/10' },
  { key: 'rose', label: 'красная', cls: 'border-rose-500/40 bg-rose-500/10' },
]

export const labelClass = (color: string): string =>
  COLORS.find((c) => c.key === color)?.cls ?? COLORS[0].cls

function LabelsSection({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [color, setColor] = useState('slate')
  const q = useQuery({
    queryKey: ['task-labels', companyId],
    queryFn: () => tasksService.listTaskLabels(companyId),
  })
  const done = () => {
    setName('')
    qc.invalidateQueries({ queryKey: ['task-labels'] })
  }
  const add = useMutation({
    mutationFn: () => tasksService.createTaskLabel(companyId, name.trim(), color),
    onSuccess: done,
    onError: (e) => toast.error((e as Error).message),
  })
  const remove = useMutation({
    mutationFn: (id: string) => tasksService.deleteTaskLabel(id, companyId),
    onSuccess: done,
    onError: (e) => toast.error((e as Error).message),
  })
  const labels = q.data?.labels ?? []

  return (
    <div className="space-y-3 p-4">
      <div>
        <h1 className="text-lg font-semibold">Метки</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Свободные ярлыки поверх типа и стадии: по ним отбирают в реестре. Метку
          заводит любой участник, удаляет — администратор пространства.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
          placeholder="Название метки" className="h-8 w-[220px] text-xs"
          onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) add.mutate() }} />
        <Select value={color} onValueChange={setColor}>
          <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {COLORS.map((c) => <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button size="sm" className="h-8" disabled={!name.trim() || add.isPending}
          onClick={() => add.mutate()}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />Завести
        </Button>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка меток…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить метки" onRetry={() => void q.refetch()} />
      ) : labels.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Меток пока нет. Заведите первую — например «срочно к отчёту» или «ждём подрядчика».
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {labels.map((l) => (
            <span key={l.id}
              className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs',
                labelClass(l.color))}>
              {l.name}
              <button type="button" aria-label={`Удалить метку ${l.name}`}
                disabled={remove.isPending} onClick={() => remove.mutate(l.id)}
                className="text-muted-foreground hover:text-foreground">
                <Trash2 className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="p-2.5 text-left font-medium">{children}</th>
}
function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('p-2.5 align-top', className)}>{children}</td>
}

export default TasksSetupPage
