/* eslint-disable react-refresh/only-export-components */
/**
 * Регламент «Задач»: сохранённые представления, шаблоны и расписания.
 *
 * Три экрана одного смысла — «что и как ставится само»:
 *  · представление — сохранённый отбор реестра (свой или общий компании);
 *  · шаблон — заготовка задачи с готовым чек-листом;
 *  · расписание — когда шаблон срабатывает без человека.
 *
 * Шаблон и тип часто путают: тип — правило движения (маршрут, срок, срочность),
 * шаблон — содержание. Поэтому шаблон ссылается на тип, а не заменяет его.
 */
import { useState } from 'react'
import { useCompany } from '@/contexts/CompanyContext'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Loader2, Play, Plus, Trash2, Users2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import * as tasksService from '@/services/tasksService'
import * as docsService from '@/services/docsService'
import { PRIORITY_LABEL, dtT } from '@/components/tasks/taskWords'
import { useDocsView } from '@/pages/docs/DocsLayout'

const WEEKDAYS = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье']

function LaunchProcessDialog({ companyId, template, people, onClose, onDone }: {
  companyId: string
  template: tasksService.TaskTemplate
  people: tasksService.TaskPerson[]
  onClose: () => void
  onDone: (result: docsService.ProcessLaunchResult) => void
}) {
  const isTask = !template.doc_kind_id
  const [title, setTitle] = useState(template.title)
  const [responsibleId, setResponsibleId] = useState(template.assignee_id ?? '')
  const start = useMutation({
    mutationFn: () => docsService.startProcessTemplate(template.id, companyId, {
      responsibleId: responsibleId || undefined,
      title: isTask ? title.trim() : undefined,
    }),
    onSuccess: onDone,
    onError: (error) => toast.error((error as Error).message),
  })

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-sm gap-0 p-0 sm:max-w-sm">
        <DialogHeader className="border-b border-border/50 px-4 py-3">
          <DialogTitle className="text-sm">Запустить процесс</DialogTitle>
          <DialogDescription className="sr-only">
            Задайте тему процесса и первого ответственного сотрудника.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 p-4">
          <div className="rounded-md bg-muted/40 px-2.5 py-2 text-xs">
            <div className="font-medium">{template.name}</div>
            {template.description && (
              <div className="mt-0.5 text-muted-foreground">{template.description}</div>
            )}
          </div>
          {isTask && (
            <div className="space-y-1">
              <Label htmlFor="process-launch-title">Тема задачи</Label>
              <Input id="process-launch-title" value={title}
                onChange={(event) => setTitle(event.target.value)} maxLength={300} />
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="process-launch-responsible">
              {isTask ? 'Первый исполнитель' : 'Ответственный'}
            </Label>
            <Select value={responsibleId || 'self'}
              onValueChange={(value) => setResponsibleId(value === 'self' ? '' : value)}>
              <SelectTrigger id="process-launch-responsible"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="self">Я</SelectItem>
                {people.map((person) => (
                  <SelectItem key={person.id} value={person.id}>{person.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {isTask && (
            <p className="text-[11px] text-muted-foreground">
              Текущий исполнитель сможет передать задачу следующему сотруднику.
              Комментарии и файлы сохраняются в общей истории.
            </p>
          )}
        </div>
        <DialogFooter className="border-t border-border/50 px-4 py-3">
          <Button size="sm" onClick={() => start.mutate()}
            disabled={start.isPending || (isTask && title.trim().length < 3)}>
            {start.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Запустить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Расписание словами: человек должен читать правило, а не расшифровывать JSON. */
export function ruleText(rule: { mode?: string; at?: string; weekday?: number; day?: number }): string {
  const at = rule.at || '09:00'
  if (rule.mode === 'weekly') return `каждую неделю, в ${WEEKDAYS[rule.weekday ?? 0]} в ${at}`
  if (rule.mode === 'monthly') return `каждый месяц, ${rule.day ?? 1}-го числа в ${at}`
  return `каждый день в ${at}`
}

/* ── Представления ───────────────────────────────────────────────────── */

export function ViewsSection({ companyId, scope = 'task' }: {
  companyId: string
  scope?: 'task' | 'doc'
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const q = useQuery({
    queryKey: [scope === 'doc' ? 'doc-views' : 'task-views', companyId],
    queryFn: () => scope === 'doc'
      ? docsService.listDocViews(companyId)
      : tasksService.listTaskViews(companyId),
  })
  const drop = useMutation({
    mutationFn: (id: string) => scope === 'doc'
      ? docsService.deleteDocView(id, companyId)
      : tasksService.deleteTaskView(id, companyId),
    onSuccess: () => qc.invalidateQueries({
      queryKey: [scope === 'doc' ? 'doc-views' : 'task-views'],
    }),
    onError: (e) => toast.error((e as Error).message),
  })
  const views = q.data?.views ?? []

  return (
    <div className="space-y-3 p-4">
      <div>
        <h1 className="text-lg font-semibold">Представления</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Сохранённые отборы реестра. Свои видите только вы, общие — вся компания;
          общее заводит администратор пространства.
        </p>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка представлений…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить представления"
          onRetry={() => void q.refetch()} />
      ) : views.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Представлений нет. Настройте отбор в «Реестре» и нажмите там «Сохранить отбор» —
          он появится здесь и будет открываться одним кликом.
        </div>
      ) : (
        <div className="space-y-1">
          {views.map((v) => (
            <div key={v.id}
              className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
              <button type="button"
                onClick={() => {
                  /* Список ключей отставал от того, что кладёт кнопка «Сохранить
                     отбор»: исполнитель, проект, метка и остальное записывались в
                     представление и молча терялись при открытии — человек видел
                     не свой отбор и решал, что представления «не работают». */
                  const allowed = new Set([
                    'view', 'q', 'status', 'kind', 'date_from', 'date_to', 'f',
                    'assignee', 'author', 'project', 'version', 'sprint', 'type',
                    'object', 'priority', 'label', 'sort', 'query', 'backlog',
                  ])
                  const target = new URLSearchParams(location.search)
                  for (const key of ['doc', 'task', 'tab', 'page', ...allowed]) {
                    target.delete(key)
                  }
                  for (const [key, value] of Object.entries(v.query)) {
                    if (allowed.has(key) && value) target.set(key, value)
                  }
                  target.set('view', scope === 'doc'
                    && ['incoming', 'outgoing', 'ord', 'internal', 'all'].includes(v.query.view)
                    ? v.query.view : scope === 'doc' ? 'all' : 'errands')
                  navigate(`${scope === 'doc' ? '/docs' : '/docs/company'}?${target.toString()}`)
                }}
                className="flex-1 text-left font-medium hover:underline">
                {v.name}
              </button>
              {v.shared && (
                <span className="inline-flex items-center gap-1 rounded border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                  <Users2 className="h-3 w-3" />общее
                </span>
              )}
              <span className="text-[11px] text-muted-foreground">
                {Object.entries(v.query).map(([k, val]) => `${k}=${val}`).join(' · ') || 'без отбора'}
              </span>
              {v.can_delete !== false && (
                <Button variant="ghost" size="sm" className="h-7 px-1.5"
                  aria-label={`Удалить ${v.name}`} onClick={() => drop.mutate(v.id)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Шаблоны ─────────────────────────────────────────────────────────── */

export function TemplatesSection({ companyId }: { companyId: string }) {
  const { isCompanyAdmin } = useCompany()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState<'process' | 'task'>(isCompanyAdmin ? 'process' : 'task')
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [typeId, setTypeId] = useState('')
  const [docKindId, setDocKindId] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [priority, setPriority] = useState('')
  const [dueDays, setDueDays] = useState('')
  const [checklist, setChecklist] = useState('')
  const [launching, setLaunching] = useState<tasksService.TaskTemplate | null>(null)
  const targetKind = isCompanyAdmin ? target : 'task'

  const q = useQuery({
    queryKey: ['task-templates', companyId],
    queryFn: () => tasksService.listTaskTemplates(companyId),
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
  const kindsQ = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listKinds(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const done = () => {
    setOpen(false); setName(''); setTitle(''); setDescription('')
    setTypeId(''); setDocKindId(''); setAssigneeId(''); setPriority(''); setDueDays(''); setChecklist('')
    qc.invalidateQueries({ queryKey: ['task-templates'] })
  }
  const create = useMutation({
    mutationFn: () => tasksService.createTaskTemplate({
      companyId, name: name.trim(), title: title.trim(),
      description: description.trim() || undefined,
      typeId: targetKind === 'task' ? typeId || undefined : undefined,
      docKindId: targetKind === 'process' ? docKindId || undefined : undefined,
      assigneeId: assigneeId || undefined, priority: priority || undefined,
      dueDays: dueDays === '' ? null : Number(dueDays),
      // Пункты чек-листа — по строке на пункт: так их и пишут в жизни.
      checklist: targetKind === 'task'
        ? checklist.split('\n').map((s) => s.trim()).filter(Boolean) : [],
    }),
    onSuccess: () => { toast.success('Шаблон заведён'); done() },
    onError: (e) => toast.error((e as Error).message),
  })
  const drop = useMutation({
    mutationFn: (id: string) => tasksService.deleteTaskTemplate(id, companyId),
    onSuccess: done,
    onError: (e) => toast.error((e as Error).message),
  })
  // Пустой список заготовок означает пустое меню «Создать» по всему «Треку»:
  // человек, пришедший заводить работу, не находит ни одной готовой дорожки.
  const starter = useMutation({
    mutationFn: () => tasksService.createStarterTemplates(companyId),
    onSuccess: (r) => {
      toast.success(r.added ? `Заведено заготовок: ${r.added}` : 'Все заготовки уже есть')
      qc.invalidateQueries({ queryKey: ['task-templates'] })
      qc.invalidateQueries({ queryKey: ['task-types'] })
      qc.invalidateQueries({ queryKey: ['process-templates'] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const templates = q.data?.templates ?? []

  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Шаблоны процессов</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Шаблон запускает маршрут документа или внутреннюю задачу. Задачный
            процесс можно передавать между сотрудниками до полного выполнения.
          </p>
        </div>
        <span className="flex items-center gap-2">
          {isCompanyAdmin && (
            <Button variant="outline" size="sm" className="h-8" disabled={starter.isPending}
              onClick={() => starter.mutate()}>Завести заготовки</Button>
          )}
          <Button size="sm" className="h-8" onClick={() => setOpen((v) => !v)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />{open ? 'Свернуть' : 'Новый шаблон'}
          </Button>
        </span>
      </div>

      {open && (
        <div className="space-y-3 rounded-lg border border-dashed p-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="task-template-target">Что запускает</Label>
              <Select value={targetKind} onValueChange={(value: 'process' | 'task') => {
                setTarget(value); setTypeId(''); setDocKindId('')
              }}>
                <SelectTrigger id="task-template-target"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {isCompanyAdmin && <SelectItem value="process">Процесс документа</SelectItem>}
                  <SelectItem value="task">Задача с маршрутом</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="task-template-name">Название шаблона</Label>
              <Input id="task-template-name" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Закрытие месяца" maxLength={160} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="task-template-title">
                {targetKind === 'process' ? 'Название документа' : 'Заголовок задачи'}
              </Label>
              <Input id="task-template-title" value={title} onChange={(e) => setTitle(e.target.value)}
                placeholder="Закрыть месяц по объекту" maxLength={300} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="task-template-description">Описание</Label>
            <Textarea id="task-template-description" value={description} onChange={(e) => setDescription(e.target.value)}
              rows={2} maxLength={8000} />
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="space-y-1.5">
              {targetKind === 'process' ? (
                <>
                  <Label htmlFor="task-template-doc-kind">Вид и маршрут</Label>
                  <Select value={docKindId} onValueChange={setDocKindId}>
                    <SelectTrigger id="task-template-doc-kind"><SelectValue placeholder="Выберите вид" /></SelectTrigger>
                    <SelectContent>
                      {(kindsQ.data ?? []).filter((kind) => kind.is_active && kind.route.length > 0)
                        .map((kind) => <SelectItem key={kind.id} value={kind.id}>{kind.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </>
              ) : (
                <>
                  <Label htmlFor="task-template-type">Тип</Label>
                  <Select value={typeId || 'none'}
                    onValueChange={(v) => setTypeId(v === 'none' ? '' : v)}>
                    <SelectTrigger id="task-template-type"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Поручение</SelectItem>
                      {(typesQ.data?.types ?? []).filter((t) => t.is_active).map((t) => (
                        <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="task-template-assignee">
                {targetKind === 'process' ? 'Ответственный' : 'Исполнитель'}
              </Label>
              <Select value={assigneeId || 'none'}
                onValueChange={(v) => setAssigneeId(v === 'none' ? '' : v)}>
                <SelectTrigger id="task-template-assignee"><SelectValue placeholder="Не назначен" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">
                    {targetKind === 'process' ? 'Инициатор запуска' : 'Не назначен'}
                  </SelectItem>
                  {(peopleQ.data?.people ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className={cn('space-y-1.5', targetKind === 'process' && 'hidden')}>
              <Label htmlFor="task-template-priority">Срочность</Label>
              <Select value={priority || 'default'}
                onValueChange={(v) => setPriority(v === 'default' ? '' : v)}>
                <SelectTrigger id="task-template-priority"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">Как у типа</SelectItem>
                  {Object.entries(PRIORITY_LABEL).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="task-template-due-days">Срок, дней</Label>
              <Input id="task-template-due-days" type="number" min={0} max={365} value={dueDays}
                onChange={(e) => setDueDays(e.target.value)} placeholder="как у типа" />
            </div>
          </div>
          {targetKind === 'task' && <div className="space-y-1.5">
            <Label htmlFor="task-template-checklist">Чек-лист — по пункту на строку</Label>
            <Textarea id="task-template-checklist" value={checklist} onChange={(e) => setChecklist(e.target.value)}
              rows={3} placeholder={'Сверить остатки\nПодписать акт'} />
          </div>}
          <Button size="sm" disabled={!name.trim() || title.trim().length < 3
              || (targetKind === 'process' && !docKindId) || create.isPending}
            onClick={() => create.mutate()}>
            {create.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Сохранить шаблон
          </Button>
        </div>
      )}

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка шаблонов…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить шаблоны" onRetry={() => void q.refetch()} />
      ) : templates.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Шаблонов нет. Заготовка избавляет от переписывания одного и того же —
          например «Закрытие месяца» с чек-листом из четырёх пунктов.
        </div>
      ) : (
        <div className="space-y-1">
          {templates.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{t.name}</div>
                <div className="text-[11px] text-muted-foreground">
                  {t.title}
                  {t.doc_kind_id
                    ? ` · ${kindsQ.data?.find((kind) => kind.id === t.doc_kind_id)?.name || 'процесс документа'}`
                    : ` · ${typesQ.data?.types.find((type) => type.id === t.type_id)?.name || 'Поручение'}`}
                  {!t.doc_kind_id && t.checklist.length > 0 && ` · чек-лист: ${t.checklist.length}`}
                  {t.due_days != null && ` · срок ${t.due_days} дн.`}
                </div>
              </div>
              <Button variant="outline" size="sm" className="h-7"
                onClick={() => setLaunching(t)}>
                <Play className="mr-1.5 h-3 w-3" />Запустить
              </Button>
              {(!t.doc_kind_id || isCompanyAdmin) && <Button variant="ghost" size="sm" className="h-7 px-1.5"
                aria-label={`Удалить ${t.name}`} onClick={() => drop.mutate(t.id)}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>}
            </div>
          ))}
        </div>
      )}
      {launching && (
        <LaunchProcessDialog companyId={companyId} template={launching}
          people={peopleQ.data?.people ?? []} onClose={() => setLaunching(null)}
          onDone={(result) => {
            setLaunching(null)
            toast.success(result.kind === 'task'
              ? `Задача №${result.taskNumber} поставлена`
              : result.started
                ? `Процесс «${result.templateName}» запущен`
                : `Процесс «${result.templateName}» создан: нужна подготовка`)
            qc.invalidateQueries({ queryKey: ['docs'] })
            if (result.kind === 'task') qc.invalidateQueries({ queryKey: ['tasks'] })
          }} />
      )}
    </div>
  )
}

/* ── Повторяющиеся ───────────────────────────────────────────────────── */

export function RecurrencesSection({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [templateId, setTemplateId] = useState('')
  const [mode, setMode] = useState('monthly')
  const [at, setAt] = useState('09:00')
  const [weekday, setWeekday] = useState('0')
  const [day, setDay] = useState('1')

  const q = useQuery({
    queryKey: ['task-recurrences', companyId],
    queryFn: () => tasksService.listTaskRecurrences(companyId),
  })
  const templatesQ = useQuery({
    queryKey: ['task-templates', companyId],
    queryFn: () => tasksService.listTaskTemplates(companyId),
  })
  const done = () => qc.invalidateQueries({ queryKey: ['task-recurrences'] })
  const create = useMutation({
    mutationFn: () => tasksService.createTaskRecurrence({
      companyId, templateId,
      rule: {
        mode, at,
        weekday: mode === 'weekly' ? Number(weekday) : undefined,
        day: mode === 'monthly' ? Number(day) : undefined,
        // Пояс обязателен по смыслу: сервер живёт в UTC, а «в 9 утра» человек
        // понимает по своему времени.
        tz: 'Europe/Moscow',
      },
    }),
    onSuccess: () => { toast.success('Расписание заведено'); setTemplateId(''); done() },
    onError: (e) => toast.error((e as Error).message),
  })
  const drop = useMutation({
    mutationFn: (id: string) => tasksService.deleteTaskRecurrence(id, companyId),
    onSuccess: done,
    onError: (e) => toast.error((e as Error).message),
  })
  const rows = q.data?.recurrences ?? []
  const templates = templatesQ.data?.templates ?? []

  return (
    <div className="space-y-3 p-4">
      <div>
        <h1 className="text-lg font-semibold">Расписания</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Что ставится само: еженедельные отчёты, ежемесячные сверки, ежедневные обходы.
          Каждое срабатывание порождает новую задачу по шаблону — старая остаётся в
          истории, иначе «делали ли в прошлом месяце» ответа не имело бы.
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Расписание <span className="text-foreground">себе</span> заводит любой — это
          личная дисциплина. Регулярную работу <span className="text-foreground">другому
          человеку</span> ставит администратор пространства.
        </p>
      </div>

      {templates.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Расписание ставится на шаблон, а шаблонов пока нет — заведите их в соседнем пункте.
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed p-3">
          <div className="space-y-1.5">
            <Label htmlFor="task-schedule-template" className="text-xs">Шаблон</Label>
            <Select value={templateId} onValueChange={setTemplateId}>
              <SelectTrigger id="task-schedule-template" className="h-8 w-[220px] text-xs">
                <SelectValue placeholder="Что ставить" />
              </SelectTrigger>
              <SelectContent>
                {templates.map((t) => (
                  <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="task-schedule-mode" className="text-xs">Когда</Label>
            <Select value={mode} onValueChange={setMode}>
              <SelectTrigger id="task-schedule-mode" className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="daily">каждый день</SelectItem>
                <SelectItem value="weekly">каждую неделю</SelectItem>
                <SelectItem value="monthly">каждый месяц</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {mode === 'weekly' && (
            <div className="space-y-1.5">
              <Label htmlFor="task-schedule-weekday" className="text-xs">День недели</Label>
              <Select value={weekday} onValueChange={setWeekday}>
                <SelectTrigger id="task-schedule-weekday" className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {WEEKDAYS.map((w, i) => (
                    <SelectItem key={i} value={String(i)}>{w}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {mode === 'monthly' && (
            <div className="space-y-1.5">
              <Label htmlFor="task-schedule-day" className="text-xs">Число</Label>
              <Input id="task-schedule-day" type="number" min={1} max={28} value={day} className="h-8 w-[90px] text-xs"
                onChange={(e) => setDay(e.target.value)} />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="task-schedule-time" className="text-xs">Время</Label>
            <Input id="task-schedule-time" type="time" value={at} onChange={(e) => setAt(e.target.value)}
              className="h-8 w-[110px] text-xs" />
          </div>
          <Button size="sm" className="h-8" disabled={!templateId || create.isPending}
            onClick={() => create.mutate()}>
            <CalendarClock className="mr-1.5 h-3.5 w-3.5" />Завести
          </Button>
        </div>
      )}

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка расписаний…
        </div>
      ) : q.isError ? (
        <QueryError message="Не удалось загрузить расписания" onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">Расписаний пока нет.</p>
      ) : (
        <div className="space-y-1">
          {rows.map((r) => (
            <div key={r.id}
              className={cn('flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm',
                !r.enabled && 'opacity-60')}>
              <div className="min-w-0 flex-1">
                <div className="font-medium">{r.template}</div>
                <div className="text-[11px] text-muted-foreground">
                  {ruleText(r.rule)}
                  {r.next_run_at && ` · следующая — ${dtT(r.next_run_at)}`}
                  {r.last_run_at && ` · последняя — ${dtT(r.last_run_at)}`}
                </div>
              </div>
              <Button variant="ghost" size="sm" className="h-7 px-1.5"
                aria-label="Удалить расписание" onClick={() => drop.mutate(r.id)}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Страница «Регламент» — три секции подряд: виды задач, шаблоны, расписания.
 *
 * Секции экспортируются по отдельности (их переиспользует настройка приложения),
 * но маршрут `/tasks/regulation` ждёт готовую страницу. Пока её не было, раздел
 * открывался пустым: динамический импорт находил модуль, но не находил в нём
 * компонента.
 */
export function TasksRegulation({ view: outer }: { view?: string } = {}) {
  const { companyId } = useCompany()
  // Экраны регламента переехали в «Настройку», но прежний маршрут остался
  // рабочим: разрез приходит снаружи, а без него берётся из старого адреса.
  const routed = useDocsView('/docs/regulation')
  const view = outer ?? routed
  if (view === 'views') return <ViewsSection companyId={companyId} scope="doc" />
  if (view === 'recurrences') return <RecurrencesSection companyId={companyId} />
  return <TemplatesSection companyId={companyId} />
}
