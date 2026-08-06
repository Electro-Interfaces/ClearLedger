/**
 * Карточка задачи — рабочее место внутри одной работы.
 *
 * Три зоны, как в любом трекере: содержание (заголовок, описание, чек-лист,
 * вложения, связи), атрибуты (тип, стадия, исполнитель, срок, метки,
 * наблюдатели) и общая лента снизу, где события и реплики идут одним потоком.
 *
 * Каждое действие может нести реплику: она прицепляется к событию, а не
 * задваивается отдельным комментарием (так сделано на сервере, не ломать).
 */
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight, CheckCircle2, Eye, EyeOff, Link2, Loader2, Mail, Paperclip, Plus,
  MessagesSquare, RefreshCw, Send, Trash2, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import * as tasksService from '@/services/tasksService'
import type { LinkKind, TaskDetails } from '@/services/tasksService'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import { listSpaceConnectors } from '@/services/spaceConnectorsService'
import { ensureTaskRoom } from '@/services/chatService'
import {
  LINK_LABEL, PRIORITY_LABEL, PRIORITY_TONE, STATUS_LABEL, WAITING_LABEL,
  dt, dtT, eventText, fileSize,
} from './taskWords'

export function TaskCard({ id, companyId, onChanged, onOpenOther }: {
  id: string; companyId: string; onChanged: () => void
  onOpenOther?: (taskId: string) => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [note, setNote] = useState('')
  const [onlyComments, setOnlyComments] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const q = useQuery({
    queryKey: ['task', id, companyId],
    queryFn: () => tasksService.taskDetails(id, companyId),
  })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const labelsQ = useQuery({
    queryKey: ['task-labels', companyId],
    queryFn: () => tasksService.listTaskLabels(companyId),
    staleTime: 5 * 60 * 1000,
  })

  const reload = () => {
    qc.invalidateQueries({ queryKey: ['task', id] })
    onChanged()
  }
  const act = useMutation({
    mutationFn: (data: Parameters<typeof tasksService.taskAction>[1]) =>
      tasksService.taskAction(id, data),
    onSuccess: (r) => {
      setNote('')
      // Сервер не отказывает, а предупреждает: закрыть родителя при живых
      // подзадачах можно, но человек обязан об этом узнать.
      if (r.warning) toast.warning(r.warning)
      if (r.mentioned?.length) toast.info(`В наблюдатели добавлены: ${r.mentioned.join(', ')}`)
      reload()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  // Комната задачи создаётся при первом обращении: заводить её каждой задаче
  // заранее — плодить пустые чаты, которые никто не откроет.
  const discuss = useMutation({
    mutationFn: () => ensureTaskRoom(id),
    onSuccess: (room) => navigate(`/messages?room=${room.id}`),
    onError: (e) => toast.error((e as Error).message),
  })
  const upload = useMutation({
    mutationFn: (file: File) => tasksService.uploadTaskFile(id, companyId, file),
    onSuccess: () => { toast.success('Файл приложен'); reload() },
    onError: (e) => toast.error(`Не удалось приложить файл: ${(e as Error).message}`),
  })

  const t = q.data
  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Загрузка задачи…
      </div>
    )
  }
  if (q.isError || !t) {
    return (
      <div className="p-6">
        <QueryError message="Не удалось загрузить задачу" onRetry={() => void q.refetch()} />
      </div>
    )
  }

  const origin = t.events.find(
    (e) => e.kind === 'created' && e.from && e.from.includes('-'))?.from ?? null
  const live = t.status === 'open'
  const stageIndex = t.route.findIndex((s) => s.code === t.stage_code)
  const next = stageIndex >= 0 ? t.route[stageIndex + 1] : t.route[0]
  const events = onlyComments ? t.events.filter((e) => e.kind === 'comment') : t.events

  return (
    <div className="flex h-full flex-col">
      <Header task={t} companyId={companyId}
        onRename={(title) => act.mutate({ companyId, title })} />

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 text-sm">
        {/* Обсуждение отдельно от ленты: лента — след работы (кто двинул, чем
            подтвердил), а короткие «когда сможешь?» её только засоряют. Кнопка
            открывает скрытую группу задачи — как у заявок. */}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" className="h-8" disabled={discuss.isPending}
            onClick={() => discuss.mutate()}>
            {discuss.isPending
              ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              : <MessagesSquare className="mr-1.5 h-3.5 w-3.5" />}
            Обсудить в чате
          </Button>
          {origin && (
            <button type="button" onClick={() => navigate(`/messages?room=${origin}`)}
              className="text-[11px] text-muted-foreground hover:text-foreground hover:underline">
              задача из обсуждения — открыть разговор
            </button>
          )}
        </div>

        {live && (
          <div className="flex flex-wrap items-center gap-2">
            {next && (
              <Button size="sm" className="h-8" disabled={act.isPending}
                onClick={() => act.mutate({
                  companyId, stageCode: next.code, note: note || undefined,
                })}>
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

        {/* Маршрут: где задача сейчас и что дальше. Полоса, а не выпадающий
            список — человек должен видеть весь путь, а не текущий шаг. */}
        <Section title="Маршрут">
          <div className="flex flex-wrap items-center gap-1">
            {t.route.map((s, i) => (
              <span key={s.code} className="flex items-center gap-1">
                {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                <button type="button" disabled={!live || act.isPending}
                  onClick={() => act.mutate({
                    companyId, stageCode: s.code, note: note || undefined,
                  })}
                  className={cn('rounded-md border px-2 py-0.5 text-[11px] transition-colors',
                    s.code === t.stage_code
                      ? 'border-primary bg-primary/10 font-medium text-foreground'
                      : 'text-muted-foreground hover:bg-muted/60',
                    !live && 'cursor-default opacity-60')}>
                  {s.name}
                </button>
              </span>
            ))}
          </div>
        </Section>

        <Description task={t} disabled={!live || act.isPending}
          onSave={(description) => act.mutate({ companyId, description })} />

        <Checklist task={t} companyId={companyId} live={live} onChanged={reload} />

        <Attributes task={t} companyId={companyId} live={live}
          people={peopleQ.data?.people ?? []} labels={labelsQ.data?.labels ?? []}
          pending={act.isPending} onAct={(d) => act.mutate(d)} onChanged={reload} />

        <Links task={t} companyId={companyId} live={live}
          onChanged={reload} onOpenOther={onOpenOther} />

        <External task={t} companyId={companyId} live={live} onChanged={reload} />

        <Section title="Файлы">
          <input ref={fileRef} type="file" className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) upload.mutate(f)
              e.target.value = ''
            }} />
          <div className="space-y-1">
            {t.attachments.map((a) => (
              <div key={a.id} className="flex items-center gap-2 text-xs">
                <Paperclip className="h-3 w-3 shrink-0 text-muted-foreground" />
                <a href={tasksService.taskFileUrl(a.id, companyId)}
                  target="_blank" rel="noreferrer"
                  className="truncate text-primary hover:underline">{a.file_name}</a>
                <span className="shrink-0 text-muted-foreground">{fileSize(a.size)}</span>
                {live && (
                  <Button variant="ghost" size="sm" className="ml-auto h-6 px-1.5"
                    aria-label="Убрать файл"
                    onClick={() => tasksService.deleteTaskFile(t.id, a.id, companyId).then(reload)}>
                    <Trash2 className="h-3 w-3" />
                  </Button>
                )}
              </div>
            ))}
            {t.attachments.length === 0 && (
              <p className="text-xs text-muted-foreground">Файлов нет.</p>
            )}
          </div>
          {live && (
            <Button variant="outline" size="sm" className="mt-2 h-7"
              disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
              {upload.isPending
                ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                : <Paperclip className="mr-1.5 h-3 w-3" />}
              Приложить файл
            </Button>
          )}
        </Section>

        {/* Единая лента: события и реплики одним потоком — иначе «почему стоит»
            приходится собирать из двух списков. */}
        <Section title="Лента" action={
          <button type="button" onClick={() => setOnlyComments((v) => !v)}
            className="text-[11px] text-muted-foreground hover:text-foreground">
            {onlyComments ? 'показать всё' : 'только реплики'}
          </button>
        }>
          <div className="space-y-2">
            {events.map((e) => (
              <div key={e.id}
                className={cn('rounded-md border px-3 py-1.5 text-xs',
                  // Реплика из письма помечена: автор должен понимать, что человек
                  // писал не отсюда и мог не видеть остального контекста.
                  e.kind === 'mail'
                    ? 'border-sky-500/40 bg-sky-500/5'
                    : 'border-border/70 bg-card/60')}>
                <div className="flex flex-wrap items-baseline gap-1.5">
                  <span className="font-medium">{e.user ?? 'система'}</span>
                  <span className="text-muted-foreground">{eventText(e)}</span>
                  {e.kind === 'mail' && (
                    <span className="inline-flex items-center gap-0.5 rounded border border-sky-500/40 px-1 text-[10px] text-sky-700 dark:text-sky-300">
                      <Mail className="h-2.5 w-2.5" />письмом
                    </span>
                  )}
                  <span className="ml-auto text-[11px] text-muted-foreground">{dtT(e.created_at)}</span>
                </div>
                {e.note && <div className="mt-0.5 whitespace-pre-wrap text-foreground/90">{e.note}</div>}
                {e.kind === 'mail' && e.to && (
                  // Первоисточник остаётся в архиве Поддержки: из ленты должна быть
                  // возможность дойти до оригинала, а не только до вычищенного текста.
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    оригинал письма в архиве Поддержки: {e.to}
                  </div>
                )}
              </div>
            ))}
            {events.length === 0 && (
              <p className="text-xs text-muted-foreground">Реплик пока нет.</p>
            )}
          </div>
        </Section>
      </div>

      {live && (
        <div className="border-t px-5 py-3">
          <div className="flex items-end gap-2">
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
              maxLength={2000} className="text-sm"
              placeholder="Написать в ленту. @имя — добавит человека в наблюдатели. Уйдёт вместе с действием." />
            <Button size="sm" className="h-8" disabled={!note.trim() || act.isPending}
              onClick={() => act.mutate({ companyId, note: note.trim() })}>Записать</Button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Шапка: номер, тип, заголовок правится на месте ──────────────────── */

function Header({ task, onRename }: {
  task: TaskDetails; companyId: string; onRename: (title: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(task.title)
  return (
    <div className="border-b px-5 py-4">
      <div className="flex items-center gap-2">
        <span className="text-base font-semibold">№{task.number}</span>
        {task.type && <Badge variant="outline" className="h-5 px-1.5 text-[11px]">{task.type}</Badge>}
        <span className="text-[11px] text-muted-foreground">
          {STATUS_LABEL[task.status] ?? task.status}
        </span>
        {task.labels.map((l) => (
          <span key={l.id}
            className="rounded border border-border/60 bg-muted/40 px-1 py-px text-[11px]">
            {l.name}
          </span>
        ))}
      </div>
      {editing ? (
        <div className="mt-1 flex gap-2">
          <Input value={title} autoFocus maxLength={300} className="h-8 text-sm"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && title.trim().length >= 3) {
                onRename(title.trim()); setEditing(false)
              }
              if (e.key === 'Escape') { setTitle(task.title); setEditing(false) }
            }} />
          <Button size="sm" className="h-8" disabled={title.trim().length < 3}
            onClick={() => { onRename(title.trim()); setEditing(false) }}>Сохранить</Button>
        </div>
      ) : (
        <button type="button" onClick={() => { setTitle(task.title); setEditing(true) }}
          className="mt-1 text-left text-sm hover:underline" title="Изменить заголовок">
          {task.title}
        </button>
      )}
    </div>
  )
}

/* ── Описание ────────────────────────────────────────────────────────── */

function Description({ task, disabled, onSave }: {
  task: TaskDetails; disabled: boolean; onSave: (text: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(task.description ?? '')
  if (editing) {
    return (
      <Section title="Описание">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={4}
          maxLength={8000} className="text-sm" autoFocus />
        <div className="mt-2 flex gap-2">
          <Button size="sm" className="h-7" onClick={() => { onSave(text); setEditing(false) }}>
            Сохранить
          </Button>
          <Button size="sm" variant="ghost" className="h-7"
            onClick={() => { setText(task.description ?? ''); setEditing(false) }}>Отмена</Button>
        </div>
      </Section>
    )
  }
  return (
    <Section title="Описание" action={!disabled && (
      <button type="button" onClick={() => { setText(task.description ?? ''); setEditing(true) }}
        className="text-[11px] text-muted-foreground hover:text-foreground">изменить</button>
    )}>
      {task.description
        ? <p className="whitespace-pre-wrap text-sm text-foreground/90">{task.description}</p>
        : <p className="text-xs text-muted-foreground">Описания нет.</p>}
    </Section>
  )
}

/* ── Чек-лист ────────────────────────────────────────────────────────── */

function Checklist({ task, companyId, live, onChanged }: {
  task: TaskDetails; companyId: string; live: boolean; onChanged: () => void
}) {
  const [text, setText] = useState('')
  const add = useMutation({
    mutationFn: () => tasksService.addChecklistItem(task.id, companyId, text.trim()),
    onSuccess: () => { setText(''); onChanged() },
    onError: (e) => toast.error((e as Error).message),
  })
  const toggle = useMutation({
    mutationFn: (v: { itemId: string; done: boolean }) =>
      tasksService.updateChecklistItem(task.id, v.itemId, { companyId, done: v.done }),
    onSuccess: onChanged,
    onError: (e) => toast.error((e as Error).message),
  })
  const remove = useMutation({
    mutationFn: (itemId: string) =>
      tasksService.deleteChecklistItem(task.id, itemId, companyId),
    onSuccess: onChanged,
  })
  const items = task.checklist_items ?? []

  return (
    <Section title={`Чек-лист${items.length ? ` · ${task.checklist.done} из ${task.checklist.total}` : ''}`}>
      <div className="space-y-1">
        {items.map((c) => (
          <div key={c.id} className="flex items-center gap-2">
            <Checkbox checked={c.done} disabled={!live || toggle.isPending}
              aria-label={c.text}
              onCheckedChange={(v) => toggle.mutate({ itemId: c.id, done: !!v })} />
            <span className={cn('flex-1 text-xs',
              c.done && 'text-muted-foreground line-through')}>{c.text}</span>
            {live && (
              <Button variant="ghost" size="sm" className="h-6 px-1.5"
                aria-label="Удалить пункт" onClick={() => remove.mutate(c.id)}>
                <Trash2 className="h-3 w-3" />
              </Button>
            )}
          </div>
        ))}
        {items.length === 0 && <p className="text-xs text-muted-foreground">Пунктов нет.</p>}
      </div>
      {live && (
        <div className="mt-2 flex gap-2">
          <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
            placeholder="Добавить пункт" className="h-7 text-xs"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && text.trim() && !add.isPending) add.mutate()
            }} />
          <Button size="sm" variant="outline" className="h-7"
            disabled={!text.trim() || add.isPending} onClick={() => add.mutate()}>
            <Plus className="h-3 w-3" />
          </Button>
        </div>
      )}
    </Section>
  )
}

/* ── Атрибуты ────────────────────────────────────────────────────────── */

function Attributes({ task, companyId, live, people, labels, pending, onAct, onChanged }: {
  task: TaskDetails; companyId: string; live: boolean
  people: { id: string; name: string }[]
  labels: { id: string; name: string }[]
  pending: boolean
  onAct: (d: Parameters<typeof tasksService.taskAction>[1]) => void
  onChanged: () => void
}) {
  const objectsQ = useQuery({
    queryKey: ['space-objects', companyId],
    queryFn: () => listSpaceObjects(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const watch = useMutation({
    mutationFn: (v: { userId: string; on: boolean }) => v.on
      ? tasksService.addWatcher(task.id, companyId, v.userId)
      : tasksService.removeWatcher(task.id, v.userId, companyId),
    onSuccess: onChanged,
    onError: (e) => toast.error((e as Error).message),
  })
  const label = useMutation({
    mutationFn: (v: { id: string; on: boolean }) => tasksService.taskAction(task.id, {
      companyId, addLabelId: v.on ? v.id : undefined,
      removeLabelId: v.on ? undefined : v.id,
    }),
    onSuccess: onChanged,
    onError: (e) => toast.error((e as Error).message),
  })
  const own = new Set(task.labels.map((l) => l.id))

  return (
    <Section title="Атрибуты">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs">Исполнитель</Label>
          <Select value={task.assignee_id ?? 'none'} disabled={!live || pending}
            onValueChange={(v) => onAct({ companyId, assigneeId: v === 'none' ? null : v })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Не назначен" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Не назначен</SelectItem>
              {people.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Срочность</Label>
          <Select value={task.priority} disabled={!live || pending}
            onValueChange={(v) => onAct({ companyId, priority: v })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(PRIORITY_LABEL).map(([k, v]) => (
                <SelectItem key={k} value={k}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Срок</Label>
          <Input type="date" disabled={!live || pending} className="h-8 text-xs"
            defaultValue={task.due_at ? task.due_at.slice(0, 10) : ''}
            onChange={(e) => e.target.value && onAct({
              companyId, dueAt: new Date(`${e.target.value}T00:00`).toISOString(),
            })} />
          {task.overdue && (
            <p className="text-[11px] font-medium text-red-600 dark:text-red-400">
              просрочена · {dt(task.due_at)}
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Объект</Label>
          <Select value={task.object_id ?? 'none'} disabled={!live || pending}
            onValueChange={(v) => onAct({ companyId, objectId: v === 'none' ? null : v })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Без объекта" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Без объекта</SelectItem>
              {(objectsQ.data ?? []).map((o) => (
                <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <Fact label="Автор" value={task.author ?? '—'} />
        <Fact label="Поставлена" value={dtT(task.created_at)} />
        <Fact label="Срочность" value={PRIORITY_LABEL[task.priority] ?? task.priority}
          tone={PRIORITY_TONE[task.priority]} />
        <Fact label="Обновлена" value={dtT(task.updated_at)} />
      </dl>

      {labels.length > 0 && (
        <div className="mt-3">
          <Label className="text-xs">Метки</Label>
          <div className="mt-1 flex flex-wrap gap-1">
            {labels.map((l) => (
              <button key={l.id} type="button" disabled={!live || label.isPending}
                onClick={() => label.mutate({ id: l.id, on: !own.has(l.id) })}
                className={cn('rounded border px-1.5 py-0.5 text-[11px] transition-colors',
                  own.has(l.id)
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted/60')}>
                {l.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3">
        <Label className="text-xs">Наблюдатели</Label>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
          {task.watchers.map((w) => (
            <span key={w.user_id}
              className="inline-flex items-center gap-1 rounded border border-border/60 bg-muted/30 px-1.5 py-0.5">
              <Eye className="h-3 w-3 text-muted-foreground" />
              {w.name}
              <span className="text-[10px] text-muted-foreground">
                {w.reason === 'mention' ? 'по упоминанию' : ''}
              </span>
              {live && (
                <button type="button" aria-label={`Отписать ${w.name}`}
                  onClick={() => watch.mutate({ userId: w.user_id, on: false })}>
                  <EyeOff className="h-3 w-3 text-muted-foreground hover:text-foreground" />
                </button>
              )}
            </span>
          ))}
          {task.watchers.length === 0 && (
            <span className="text-muted-foreground">Никто не следит.</span>
          )}
          {live && (
            <Select onValueChange={(v) => watch.mutate({ userId: v, on: true })}>
              <SelectTrigger className="h-7 w-[150px] text-[11px]">
                <SelectValue placeholder="+ наблюдатель" />
              </SelectTrigger>
              <SelectContent>
                {people.filter((p) => !task.watchers.some((w) => w.user_id === p.id))
                  .map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
        </div>
      </div>
    </Section>
  )
}

/* ── Связи и подзадачи ───────────────────────────────────────────────── */

function Links({ task, companyId, live, onChanged, onOpenOther }: {
  task: TaskDetails; companyId: string; live: boolean
  onChanged: () => void; onOpenOther?: (id: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<LinkKind>('subtask')

  // Ищем по той же ручке, что и реестр: отдельного поиска «для связи» не заводим.
  const found = useQuery({
    queryKey: ['tasks-search', companyId, query],
    queryFn: () => tasksService.listTasks(companyId, 'all', { q: query, limit: 8 }),
    enabled: adding && query.trim().length >= 2,
  })
  const add = useMutation({
    mutationFn: (relatedTaskId: string) =>
      tasksService.addTaskLink(task.id, { companyId, relatedTaskId, kind }),
    onSuccess: () => { setAdding(false); setQuery(''); onChanged() },
    onError: (e) => toast.error((e as Error).message),
  })
  const remove = useMutation({
    mutationFn: (linkId: string) => tasksService.deleteTaskLink(task.id, linkId, companyId),
    onSuccess: onChanged,
  })

  return (
    <Section title="Связи и подзадачи" action={live && (
      <button type="button" onClick={() => setAdding((v) => !v)}
        className="text-[11px] text-muted-foreground hover:text-foreground">
        {adding ? 'отмена' : 'связать'}
      </button>
    )}>
      {adding && (
        <div className="mb-2 space-y-2 rounded-md border border-dashed p-2">
          <div className="flex gap-2">
            <Select value={kind} onValueChange={(v) => setKind(v as LinkKind)}>
              <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="subtask">подзадача</SelectItem>
                <SelectItem value="blocks">блокирует</SelectItem>
                <SelectItem value="relates">связана</SelectItem>
                <SelectItem value="duplicates">дублирует</SelectItem>
              </SelectContent>
            </Select>
            <Input value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Номер или слова из заголовка" className="h-7 flex-1 text-xs" />
          </div>
          <div className="space-y-1">
            {(found.data?.tasks ?? []).filter((x) => x.id !== task.id).map((x) => (
              <button key={x.id} type="button" disabled={add.isPending}
                onClick={() => add.mutate(x.id)}
                className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-muted/60">
                <Link2 className="h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="shrink-0 font-medium">№{x.number}</span>
                <span className="truncate">{x.title}</span>
              </button>
            ))}
            {query.trim().length >= 2 && found.data?.tasks.length === 0 && (
              <p className="text-[11px] text-muted-foreground">Ничего не нашлось.</p>
            )}
          </div>
        </div>
      )}
      <div className="space-y-1">
        {task.links.map((l) => (
          <div key={`${l.id}-${l.kind}`} className="flex items-center gap-2 text-xs">
            <span className="w-[104px] shrink-0 text-muted-foreground">
              {LINK_LABEL[l.kind] ?? l.kind}
            </span>
            <button type="button" onClick={() => onOpenOther?.(l.task_id)}
              className="truncate text-left hover:underline">
              <span className="font-medium">№{l.number}</span> {l.title}
            </button>
            <span className={cn('shrink-0 text-[11px]',
              l.status === 'open' ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
              {STATUS_LABEL[l.status] ?? l.status}
            </span>
            {live && (
              <Button variant="ghost" size="sm" className="ml-auto h-6 px-1.5"
                aria-label="Снять связь" onClick={() => remove.mutate(l.id)}>
                <Trash2 className="h-3 w-3" />
              </Button>
            )}
          </div>
        ))}
        {task.links.length === 0 && !adding && (
          <p className="text-xs text-muted-foreground">Связей нет.</p>
        )}
      </div>
    </Section>
  )
}

/* ── Внешние участники: разговор каналом ─────────────────────────────── */

function External({ task, companyId, live, onChanged }: {
  task: TaskDetails; companyId: string; live: boolean; onChanged: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [note, setNote] = useState('')

  const delegate = useMutation({
    mutationFn: () => tasksService.delegateByMail(task.id, {
      companyId, email: email.trim(), name: name.trim() || undefined,
      note: note.trim() || undefined,
    }),
    onSuccess: (r) => {
      toast.success(`Поручение ушло на ${r.email}`)
      setAdding(false); setEmail(''); setName(''); setNote('')
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const drop = useMutation({
    mutationFn: (userId: string) =>
      tasksService.removeParticipant(task.id, userId, companyId),
    onSuccess: onChanged,
    onError: (e) => toast.error((e as Error).message),
  })

  return (
    <Section title="Внешние участники" action={live && (
      <button type="button" onClick={() => setAdding((v) => !v)}
        className="text-[11px] text-muted-foreground hover:text-foreground">
        {adding ? 'отмена' : 'поручить наружу'}
      </button>
    )}>
      {task.waiting_for === 'external' && (
        // Состояние «мяч у внешней стороны» видимое: задача не брошена, но и не
        // висит «на мне» — иначе список «что делать» полон тем, чего сделать нельзя.
        <div className="mb-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-2.5 py-1.5 text-xs">
          <Send className="mr-1 inline h-3 w-3 text-amber-600 dark:text-amber-400" />
          {WAITING_LABEL.external} — задача ждёт ответа и не показывается в «На мне».
        </div>
      )}

      {adding && (
        <div className="mb-2 space-y-2 rounded-md border border-dashed p-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <Input value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="Почта подрядчика" className="h-7 text-xs" type="email" />
            <Input value={name} onChange={(e) => setName(e.target.value)}
              placeholder="Как его зовут" className="h-7 text-xs" maxLength={120} />
          </div>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
            maxLength={2000} className="text-xs"
            placeholder="Что нужно сделать — уйдёт в письмо" />
          <div className="flex items-center gap-2">
            <Button size="sm" className="h-7"
              disabled={!email.includes('@') || delegate.isPending}
              onClick={() => delegate.mutate()}>
              {delegate.isPending
                ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                : <Send className="mr-1.5 h-3 w-3" />}
              Отправить письмом
            </Button>
            <span className="text-[11px] text-muted-foreground">
              Ответ вернётся сюда репликой с пометкой «письмом».
            </span>
          </div>
        </div>
      )}

      <div className="space-y-1">
        {task.participants.map((p) => (
          <div key={p.user_id} className="flex items-center gap-2 text-xs">
            <Mail className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="font-medium">{p.name}</span>
            <span className="truncate text-muted-foreground">{p.channel_ref ?? p.email}</span>
            <span className="shrink-0 rounded border border-border/60 px-1 py-px text-[10px] text-muted-foreground">
              {p.channel === 'mail' ? 'письмом' : p.channel === 'connector' ? 'коннектор' : 'в пространстве'}
            </span>
            {live && (
              <Button variant="ghost" size="sm" className="ml-auto h-6 px-1.5"
                aria-label={`Убрать ${p.name}`} onClick={() => drop.mutate(p.user_id)}>
                <Trash2 className="h-3 w-3" />
              </Button>
            )}
          </div>
        ))}
        {task.participants.length === 0 && !adding && (
          <p className="text-xs text-muted-foreground">
            Внешних участников нет. Подрядчику можно поручить письмом — заходить в
            пространство ему для этого не нужно.
          </p>
        )}
      </div>
      {task.reply_address && task.participants.length > 0 && (
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          Адрес ответа: {task.reply_address}
        </p>
      )}
      {!task.reply_address && adding && (
        // Канал, который не настроен, обязан честно говорить о себе.
        <p className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400">
          В пространстве не настроен ящик приёма — письмо отправить некуда.
        </p>
      )}

      <ExternalSystem task={task} companyId={companyId} live={live} onChanged={onChanged} />
    </Section>
  )
}

/** Работа во внешней системе: зеркало, а не копия. */
function ExternalSystem({ task, companyId, live, onChanged }: {
  task: TaskDetails; companyId: string; live: boolean; onChanged: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [key, setKey] = useState('')
  const [number, setNumber] = useState('')
  const [url, setUrl] = useState('')

  const connectorsQ = useQuery({
    queryKey: ['space-connectors', companyId],
    queryFn: () => listSpaceConnectors(companyId),
    enabled: adding, staleTime: 60 * 1000,
  })
  // Делегировать можно только туда, где живёт чужая работа: файловый канал
  // Учёта и платформенные сервисы — не внешние исполнители.
  const usable = (connectorsQ.data?.connectors ?? []).filter(
    (c) => c.app !== 'ledger' && c.app !== 'core' && c.enabled)

  const link = useMutation({
    mutationFn: () => tasksService.linkExternal(task.id, {
      companyId, connectorKey: key, externalNumber: number.trim() || undefined,
      externalUrl: url.trim() || undefined,
      connectorLabel: usable.find((c) => c.key === key)?.label,
    }),
    onSuccess: () => {
      toast.success('Работа связана с внешней системой')
      setAdding(false); setKey(''); setNumber(''); setUrl('')
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const sync = useMutation({
    mutationFn: (refId: string) => tasksService.syncExternal(task.id, refId, companyId),
    onSuccess: (r) => {
      // Приложение может не отдавать состояние — говорим прямо, а не молчим.
      if (!r.ok) toast.warning(r.reason ?? 'Состояние получить не удалось')
      else toast.success(r.stages_added
        ? `Обновлено, новых этапов: ${r.stages_added}` : 'Состояние обновлено')
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const drop = useMutation({
    mutationFn: (refId: string) => tasksService.unlinkExternal(task.id, refId, companyId),
    onSuccess: onChanged,
  })

  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Внешняя система</span>
        {live && (
          <button type="button" onClick={() => setAdding((v) => !v)}
            className="text-[11px] text-muted-foreground hover:text-foreground">
            {adding ? 'отмена' : 'связать с работой'}
          </button>
        )}
      </div>

      {adding && (
        <div className="mb-2 space-y-2 rounded-md border border-dashed p-2">
          <Select value={key} onValueChange={setKey}>
            <SelectTrigger className="h-7 text-xs">
              <SelectValue placeholder={connectorsQ.isLoading
                ? 'Загрузка подключений…' : 'Куда делегируем'} />
            </SelectTrigger>
            <SelectContent>
              {usable.map((c) => (
                <SelectItem key={c.key} value={c.key}>
                  {c.label} · {c.app_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!connectorsQ.isLoading && usable.length === 0 && (
            <p className="text-[11px] text-amber-600 dark:text-amber-400">
              У компании нет живых подключений к внешним системам. Их заводят в
              приложении-владельце, а не здесь.
            </p>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            <Input value={number} onChange={(e) => setNumber(e.target.value)}
              placeholder="Их номер работы" className="h-7 text-xs" />
            <Input value={url} onChange={(e) => setUrl(e.target.value)}
              placeholder="Ссылка на их карточку" className="h-7 text-xs" />
          </div>
          <Button size="sm" className="h-7" disabled={!key || link.isPending}
            onClick={() => link.mutate()}>
            {link.isPending && <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />}
            Связать
          </Button>
        </div>
      )}

      <div className="space-y-1">
        {task.external.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center gap-2 text-xs">
            <Link2 className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="font-medium">{r.connector_label ?? r.connector_key}</span>
            {r.external_number && (
              r.external_url
                ? <a href={r.external_url} target="_blank" rel="noreferrer"
                  className="text-primary hover:underline">{r.external_number}</a>
                : <span>{r.external_number}</span>
            )}
            <span className="text-muted-foreground">
              {r.external_status ?? 'состояние не получено'}
            </span>
            {r.last_sync_at && (
              <span className="text-[10px] text-muted-foreground">
                сверено {dtT(r.last_sync_at)}
              </span>
            )}
            {live && (
              <span className="ml-auto flex items-center gap-1">
                <Button variant="ghost" size="sm" className="h-6 px-1.5"
                  aria-label="Сверить состояние" disabled={sync.isPending}
                  onClick={() => sync.mutate(r.id)}>
                  <RefreshCw className={cn('h-3 w-3', sync.isPending && 'animate-spin')} />
                </Button>
                <Button variant="ghost" size="sm" className="h-6 px-1.5"
                  aria-label="Снять связь" onClick={() => drop.mutate(r.id)}>
                  <Trash2 className="h-3 w-3" />
                </Button>
              </span>
            )}
          </div>
        ))}
        {task.external.length === 0 && !adding && (
          <p className="text-xs text-muted-foreground">
            Во внешние системы не делегировано. Работу заводит их владелец, здесь
            остаётся связь с ней — второй правды о чужой работе не держим.
          </p>
        )}
      </div>
    </div>
  )
}

/* ── Мелочи ──────────────────────────────────────────────────────────── */

function Section({ title, action, children }: {
  title: string; action?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{title}</span>
        {action}
      </div>
      {children}
    </div>
  )
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('mt-0.5 text-foreground', tone)}>{value}</dd>
    </div>
  )
}

export default TaskCard
