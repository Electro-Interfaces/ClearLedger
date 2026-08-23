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
import { useSupportContext } from '@/contexts/SupportContext'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, CheckCircle2, ChevronRight, Clock, Eye, EyeOff, Link2,
  Loader2, Lock, Mail, MessagesSquare, Paperclip, Pin, Plus, RefreshCw, Send, Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import * as tasksService from '@/services/tasksService'
import { WorkIdentity } from '@/components/work/WorkIdentity'
import { WorkTrace } from '@/components/work/WorkTrace'
import type { LinkKind, LoadedTask } from '@/services/tasksService'
import { listSpaceObjects } from '@/services/spaceObjectsService'
import { listSpaceConnectors } from '@/services/spaceConnectorsService'
import { RichText } from './RichText'
import { SearchPicker } from './SearchPicker'
import { TaskChat } from './TaskChat'
import {
  LINK_LABEL, PRIORITY_LABEL, STATUS_LABEL, WAITING_LABEL,
  dt, dtT, eventText, fileSize,
} from './taskWords'

export function TaskCard({ id, companyId, onChanged, onOpenOther, onBack }: {
  id: string; companyId: string; onChanged: () => void
  onOpenOther?: (taskId: string) => void
  /** Возврат к списку. Есть — карточка показана экраном, нет — врезкой. */
  onBack?: () => void
}) {
  const qc = useQueryClient()
  const { openInteraction } = useSupportContext()
  const [note, setNote] = useState('')
  const [feedKind, setFeedKind] = useState<'all' | 'talk' | 'move' | 'meta'>('all')
  const [tab, setTab] = useState('work')
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
  const pin = useMutation({
    mutationFn: (eventId: string) => tasksService.pinEvent(id, eventId, companyId),
    onSuccess: reload,
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
  const shown = feedKind === 'all' ? t.events
    : feedKind === 'talk' ? t.events.filter((e) => ['comment', 'mail'].includes(e.kind))
      : feedKind === 'move' ? t.events.filter(
        (e) => ['stage', 'status', 'assign', 'created', 'delegate', 'external_stage'].includes(e.kind))
        : t.events.filter((e) => ['work', 'field'].includes(e.kind))
  // Закреплённое — наверх: договорённость, к которой возвращаются, не должна
  // тонуть в ленте из тридцати событий.
  const events = [...shown].sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned))

  return (
    <div className="flex h-full flex-col">
      <Header task={t} companyId={companyId} onBack={onBack}
        onRename={(title) => act.mutate({ companyId, title })} />

      <div className="flex min-h-0 flex-1">
      <div className={cn('flex min-w-0 flex-1 flex-col px-5 py-4 text-sm',
        tab === 'chat' ? 'overflow-hidden' : 'overflow-y-auto')}>
        {/* Маршрут первым: «где сейчас работа» — главный вопрос к карточке.
            Одинаковые пилюли одного размера, активная залита. Раньше здесь были
            три разные рамки, и полоса читалась как набор случайных плашек. */}
        <div className="flex flex-wrap items-center gap-1">
          {t.route.map((s, i) => (
            <span key={s.code} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />}
              <button type="button" disabled={!live || act.isPending}
                onClick={() => act.mutate({
                  companyId, stageCode: s.code, note: note || undefined,
                })}
                className={cn('h-7 rounded-full px-3 text-xs transition-colors',
                  s.code === t.stage_code
                    ? 'bg-primary font-medium text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:bg-muted/70 hover:text-foreground',
                  !live && 'cursor-default opacity-60')}>
                {s.name}
              </button>
            </span>
          ))}
        </div>

        {/* Действия одной линейкой: все кнопки одной высоты и двух видов —
            главное действие залито, остальные одинаковые. Разрушительное
            («Отменить задачу») отодвинуто вправо и приглушено: рядом с
            «Выполнена» ему не место. */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {live && next && (
            <Button size="sm" className="h-8" disabled={act.isPending}
              onClick={() => act.mutate({
                companyId, stageCode: next.code, note: note || undefined,
              })}>
              <ArrowRight className="mr-1.5 h-3.5 w-3.5" />{next.name}
            </Button>
          )}
          {live && (
            <Button size="sm" variant="outline" className="h-8" disabled={act.isPending}
              onClick={() => act.mutate({ companyId, status: 'done', note: note || undefined })}>
              <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />Выполнена
            </Button>
          )}
          <Button size="sm" variant="outline" className="h-8"
            onClick={() => setTab('chat')}>
            <MessagesSquare className="mr-1.5 h-3.5 w-3.5" />Обсудить
          </Button>
          {live && (
            <Button size="sm" variant="ghost"
              className="ml-auto h-8 text-muted-foreground hover:text-foreground"
              disabled={act.isPending}
              onClick={() => act.mutate({ companyId, status: 'cancelled', note: note || undefined })}>
              Отменить задачу
            </Button>
          )}
        </div>
        {origin && (
          // Разговор открывается той же панелью чата, что и кнопка «Чат» в шапке,
          // наведённой на комнату. Раньше вело на `/messages?room=` — а это админский
          // реестр чатов пространства, который параметр не читает: обычного человека
          // он не пускал вовсе, администратора приводил в таблицу без разговора.
          <button type="button" onClick={() => openInteraction('chat', `room:${origin}`)}
            className="mt-2 text-[11px] text-muted-foreground hover:text-foreground hover:underline">
            задача из обсуждения — открыть разговор
          </button>
        )}

        <Tabs value={tab} onValueChange={setTab}
          className={cn('mt-6', tab === 'chat' && 'flex min-h-0 flex-1 flex-col')}>
          {/* Вкладки вместо одной длинной колонки: у задачи с полусотней ходов
              история — отдельная работа, и ради неё не нужно прокручивать
              чек-лист и файлы. */}
          <TabsList variant="line" className="h-9 w-full justify-start gap-5 border-b border-border/60">
            <TabsTrigger value="work" className="flex-none px-0 text-[13px]">Работа</TabsTrigger>
            {/* На узком экране свойства живут вкладкой, на широком — колонкой
                справа: там они нужны постоянно, а не по клику. */}
            <TabsTrigger value="attrs" className="flex-none px-0 text-[13px] xl:hidden">Свойства</TabsTrigger>
            <TabsTrigger value="chat" className="flex-none px-0 text-[13px]">
              Обсуждение
            </TabsTrigger>
            <TabsTrigger value="links" className="flex-none px-0 text-[13px]">
              Связи{t.subtasks.total ? ` · ${t.subtasks.total}` : ''}
            </TabsTrigger>
            <TabsTrigger value="time" className="flex-none px-0 text-[13px]">
              Время{t.time.spent ? ` · ${t.time.spent_text}` : ''}
            </TabsTrigger>
            <TabsTrigger value="files" className="flex-none px-0 text-[13px]">
              Файлы{t.attachments.length ? ` · ${t.attachments.length}` : ''}
            </TabsTrigger>
            <TabsTrigger value="feed" className="flex-none px-0 text-[13px]">История · {t.events.length}</TabsTrigger>
          </TabsList>

          <TabsContent value="work" className="space-y-5 pt-4">
        <Description task={t} disabled={!live || act.isPending}
          onSave={(description) => act.mutate({ companyId, description })} />

        <Checklist task={t} companyId={companyId} live={live} onChanged={reload} />
          </TabsContent>
          <TabsContent value="attrs" className="space-y-5 pt-4 xl:hidden">
        <Attributes task={t} companyId={companyId} live={live}
          people={peopleQ.data?.people ?? []} labels={labelsQ.data?.labels ?? []}
          pending={act.isPending} onAct={(d) => act.mutate(d)} onChanged={reload} />
          </TabsContent>
          <TabsContent value="chat" className="pt-4 data-[state=active]:flex data-[state=active]:min-h-0 data-[state=active]:flex-1">
            <TaskChat taskId={t.id} taskNumber={t.number} selfName={t.assignee} />
          </TabsContent>
          <TabsContent value="links" className="space-y-5 pt-4">
        <Links task={t} companyId={companyId} live={live}
          onChanged={reload} onOpenOther={onOpenOther} />
        <CodeRefs taskId={t.id} companyId={companyId} live={live} />
        <External task={t} companyId={companyId} live={live} onChanged={reload} />
          </TabsContent>
          <TabsContent value="time" className="space-y-5 pt-4">
        <TimePanel task={t} companyId={companyId} live={live}
          onChanged={reload} onEstimate={(v) => act.mutate({ companyId, estimate: v })} />
          </TabsContent>
          <TabsContent value="files" className="space-y-5 pt-4">
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
                {live && a.can_delete && (
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
          </TabsContent>
          <TabsContent value="feed" className="space-y-5 pt-4">
        {/* Единая лента: события и реплики одним потоком — иначе «почему стоит»
            приходится собирать из двух списков. */}
        <Section title="История" action={
          <span className="flex gap-1">
            {([['all', 'всё'], ['talk', 'разговор'], ['move', 'движение'],
               ['meta', 'правки и время']] as const).map(([k, label]) => (
              <button key={k} type="button" onClick={() => setFeedKind(k)}
                className={cn('rounded px-1.5 py-0.5 text-[11px] transition-colors',
                  feedKind === k
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground hover:text-foreground')}>
                {label}
              </button>
            ))}
          </span>
        }>
          <div className="space-y-2">
            {/* След рисуется общим компонентом (этап 13е): у документа и у
                поручения один и тот же вопрос — «что делали и кто». Особенное
                приходит слотами: закрепление, пометка письма, ссылка на оригинал. */}
            <WorkTrace
              events={events.map((e) => ({
                id: e.id, at: e.created_at, actor: e.user, action: eventText(e),
                tone: e.kind === 'mail' ? 'mail' : 'default',
                note: e.note
                  ? <RichText text={e.note} className="mt-0.5 text-foreground/90" />
                  : null,
              }))}
              empty={feedKind === 'all' ? 'Ходов пока нет.' : 'В этом разрезе ходов нет.'}
              renderBadge={(event) => (event.tone === 'mail' ? (
                <span className="inline-flex items-center gap-0.5 rounded border border-sky-500/40 px-1 text-[10px] text-sky-700 dark:text-sky-300">
                  <Mail className="h-2.5 w-2.5" />письмом
                </span>
              ) : null)}
              renderActions={(event) => {
                const source = events.find((e) => e.id === event.id)
                if (!live || !source) return null
                return (
                  <button type="button" title={source.pinned ? 'Открепить' : 'Закрепить'}
                    onClick={() => pin.mutate(source.id)}
                    className={cn('shrink-0',
                      source.pinned ? 'text-primary'
                        : 'text-muted-foreground/50 hover:text-foreground')}>
                    <Pin className="h-3 w-3" />
                  </button>
                )
              }}
              renderExtra={(event) => {
                const source = events.find((e) => e.id === event.id)
                // Первоисточник остаётся в архиве Поддержки: из ленты должна быть
                // возможность дойти до оригинала, а не только до вычищенного текста.
                if (!source || source.kind !== 'mail' || !source.to) return null
                return (
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    оригинал письма в архиве Поддержки: {source.to}
                  </div>
                )
              }} />
          </div>
        </Section>
          </TabsContent>
        </Tabs>
      </div>

      {/* Свойства колонкой — только когда есть куда её положить. */}
      <aside className="hidden w-[320px] shrink-0 overflow-y-auto border-l px-4 py-4 text-sm xl:block">
        <Attributes task={t} companyId={companyId} live={live}
          people={peopleQ.data?.people ?? []} labels={labelsQ.data?.labels ?? []}
          pending={act.isPending} onAct={(d) => act.mutate(d)} onChanged={reload} />
      </aside>
      </div>

      {live && tab !== 'chat' && (
        <div className="border-t bg-muted/20 px-5 py-3">
          <div className="flex items-end gap-2">
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
              maxLength={2000} className="text-sm"
              placeholder="Написать в ленту. @имя — добавит человека в наблюдатели. Скриншот — Ctrl+V. Уйдёт вместе с действием."
              // Скриншот вставляется прямо в поле реплики: пока человек
              // объясняет, что не так, картинка уже прикладывается к задаче.
              onPaste={(e) => {
                const imgs = Array.from(e.clipboardData.files).filter(
                  (f) => f.type.startsWith('image/'))
                if (imgs.length) {
                  e.preventDefault()
                  imgs.forEach((f) => upload.mutate(f))
                }
              }} />
            <Button size="sm" className="h-8" disabled={!note.trim() || act.isPending}
              onClick={() => act.mutate({ companyId, note: note.trim() })}>Записать</Button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Шапка: номер, тип, заголовок правится на месте ──────────────────── */

function Header({ task, onRename, onBack }: {
  task: LoadedTask; companyId: string; onRename: (title: string) => void
  onBack?: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(task.title)
  return (
    <div className="border-b px-5 py-4">
      {onBack && (
        <button type="button" onClick={onBack}
          className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" />к списку
        </button>
      )}
      <div className="flex items-center gap-2">
        {/* Та же строка представления, что у документа (этап 13е): человек,
            перешедший из ленты работы, читает одни и те же слова. */}
        <WorkIdentity itemKey={tasksService.taskKey(task)} type={task.type}
          state={task.state} stateName={task.state_name}
          extra={task.project} />
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

/** Выбор версии проекта. Отменённые не предлагаются, но уже проставленная
 *  показывается — иначе поле выглядит пустым там, где значение есть. */
function VersionPick({ value, versions, disabled, onChange }: {
  value: string
  versions: tasksService.TaskVersion[]
  disabled: boolean
  onChange: (v: string | null) => void
}) {
  const items = versions.filter((v) => v.state !== 'cancelled' || v.id === value)
  return (
    <Select value={value || 'none'} disabled={disabled}
      onValueChange={(v) => onChange(v === 'none' ? null : v)}>
      <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Не указана" /></SelectTrigger>
      <SelectContent>
        <SelectItem value="none">Не указана</SelectItem>
        {items.map((v) => (
          <SelectItem key={v.id} value={v.id}>
            {v.name}{v.state === 'released' ? ' · выпущена' : ''}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/* ── Описание ────────────────────────────────────────────────────────── */

function Description({ task, disabled, onSave }: {
  task: LoadedTask; disabled: boolean; onSave: (text: string) => void
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
      {task.description ? (
        <RichText text={task.description} className="text-sm text-foreground/90" />
      ) : disabled ? (
        <p className="text-xs text-muted-foreground">Описания нет.</p>
      ) : (
        // Пустое место должно звать, а не сообщать о пустоте.
        <button type="button" onClick={() => { setText(''); setEditing(true) }}
          className="w-full rounded-lg border border-dashed px-3 py-4 text-left text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground">
          Добавить описание: что именно, где, к какому результату. Скриншот — Ctrl+V.
        </button>
      )}
    </Section>
  )
}

/* ── Чек-лист ────────────────────────────────────────────────────────── */

function Checklist({ task, companyId, live, onChanged }: {
  task: LoadedTask; companyId: string; live: boolean; onChanged: () => void
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
        {items.length === 0 && (
          <p className="text-xs text-muted-foreground">
            {live ? 'Разбейте работу на шаги — прогресс будет виден в списке.' : 'Пунктов нет.'}
          </p>
        )}
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
  task: LoadedTask; companyId: string; live: boolean
  people: tasksService.TaskPerson[]
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
  // Версии живут на проекте: у задачи без проекта выбирать не из чего, и поля
  // не показываются вовсе — пустой список хуже отсутствия поля.
  const versionsQ = useQuery({
    queryKey: ['task-versions', companyId, task.project_id],
    queryFn: () => tasksService.listTaskVersions(companyId, task.project_id ?? undefined),
    enabled: !!task.project_id, staleTime: 5 * 60 * 1000,
  })
  const versions = versionsQ.data?.versions ?? []
  const sprintsQ = useQuery({
    queryKey: ['task-sprints', companyId, task.project_id],
    queryFn: () => tasksService.listTaskSprints(companyId, task.project_id ?? undefined),
    enabled: !!task.project_id, staleTime: 5 * 60 * 1000,
  })
  const sprints = sprintsQ.data?.sprints ?? []
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
    <Section title="">
      <div className="space-y-3">
        <Field label="Исполнитель">
          <SearchPicker items={people.map((p) => ({ id: p.id, name: p.name, party: p.partyType }))}
            value={task.assignee_id ?? ''} disabled={!live || pending}
            onChange={(v) => onAct({ companyId, assigneeId: v || null })}
            placeholder="Не назначен" emptyLabel="Не назначен"
            searchPlaceholder="Фамилия или имя…" />
        </Field>
        <Field label="Срочность">
          <Select value={task.priority} disabled={!live || pending}
            onValueChange={(v) => onAct({ companyId, priority: v })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(PRIORITY_LABEL).map(([k, v]) => (
                <SelectItem key={k} value={k}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Срок"
          hint={task.overdue ? ('просрочена · ' + dt(task.due_at)) : undefined}
          tone={task.overdue ? 'text-red-600 dark:text-red-400' : undefined}>
          <Input type="date" disabled={!live || pending} className="h-8 text-xs"
            defaultValue={task.due_at ? task.due_at.slice(0, 10) : ''}
            onChange={(e) => e.target.value && onAct({
              companyId, dueAt: new Date(`${e.target.value}T00:00`).toISOString(),
            })} />
        </Field>
        <Field label="Объект">
          <SearchPicker items={(objectsQ.data ?? []).map((o) => ({
            id: o.id, name: o.name, hint: o.address }))}
            value={task.object_id ?? ''} disabled={!live || pending}
            onChange={(v) => onAct({ companyId, objectId: v || null })}
            placeholder="Без объекта" emptyLabel="Без объекта"
            searchPlaceholder="Номер, название или адрес…"
            loading={objectsQ.isLoading} width="w-[320px]" />
        </Field>
        {task.project_id && (
          <>
            <Field label="Исправлено в версии">
              <VersionPick value={task.fix_version_id ?? ''} versions={versions}
                disabled={!live || pending}
                onChange={(v) => onAct({ companyId, fixVersionId: v })} />
            </Field>
            <Field label="Обнаружено в версии">
              <VersionPick value={task.found_version_id ?? ''} versions={versions}
                disabled={!live || pending}
                onChange={(v) => onAct({ companyId, foundVersionId: v })} />
            </Field>
            <Field label="Спринт" hint={task.sprint ? undefined : "бэклог"}>
              {/* Закрытый спринт не предлагается: его итог уже подведён. */}
              <Select value={task.sprint_id ?? 'none'} disabled={!live || pending}
                onValueChange={(v) => onAct({ companyId, sprintId: v === 'none' ? null : v })}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Бэклог</SelectItem>
                  {sprints.filter((sp) => sp.state !== 'closed' || sp.id === task.sprint_id)
                    .map((sp) => (
                      <SelectItem key={sp.id} value={sp.id}>{sp.name}</SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </Field>
          </>
        )}
      </div>

      {labels.length > 0 && (
        <div className="mt-3">
          <FieldLabel>Метки</FieldLabel>
          <div className="mt-1.5 flex flex-wrap gap-1">
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
        <FieldLabel>Кто видит задачу</FieldLabel>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
          <Select value={task.visibility} disabled={!live || pending}
            onValueChange={(v) => onAct({ companyId, visibility: v as 'company' | 'private' })}>
            <SelectTrigger className="h-7 w-[200px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="company">Вся компания</SelectItem>
              <SelectItem value="private">Только причастные</SelectItem>
            </SelectContent>
          </Select>
          {task.visibility === 'private' && (
            <span className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/5 px-1.5 py-0.5 text-[11px] text-amber-700 dark:text-amber-400">
              <Lock className="h-3 w-3" />
              видят автор, исполнитель, наблюдатели и администратор
            </span>
          )}
        </div>
      </div>

      <div className="mt-3">
        <FieldLabel>Наблюдатели</FieldLabel>
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
      <dl className="mt-5 space-y-1.5 border-t pt-3 text-[11px] text-muted-foreground">
        <div className="flex justify-between gap-2">
          <dt>Автор</dt>
          <dd className="text-right text-foreground/80">{task.author ?? '—'}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>Поставлена</dt><dd className="text-right">{dtT(task.created_at)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>Обновлена</dt><dd className="text-right">{dtT(task.updated_at)}</dd>
        </div>
      </dl>
    </Section>
  )
}

/** Поле правой колонки: подпись, значение, при нужде — предупреждение снизу. */
function Field({ label, hint, tone, children }: {
  label: string; hint?: string; tone?: string; children: React.ReactNode
}) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <div className="mt-1.5">{children}</div>
      {hint && <p className={cn('mt-1 text-[11px] font-medium', tone)}>{hint}</p>}
    </div>
  )
}

/** Подпись поля: один кегль и один регистр на всю колонку. */
function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] uppercase tracking-wide text-muted-foreground/70">
      {children}
    </span>
  )
}

/* ── Связи и подзадачи ───────────────────────────────────────────────── */

/** Что сделано в коде: ветка, коммит, запрос на слияние.
 *
 *  «Исправлено в версии» отвечает заявителю, этот блок — разработчику: каким
 *  изменением. Вид ссылки узнаётся по адресу; неузнанный хостинг не отвергается,
 *  а показывается ссылкой — чужих хостингов больше, чем шаблонов, которые мы
 *  готовы поддерживать. */
function CodeRefs({ taskId, companyId, live }: {
  taskId: string; companyId: string; live: boolean
}) {
  const qc = useQueryClient()
  const [url, setUrl] = useState('')

  const q = useQuery({
    queryKey: ['task-code', taskId],
    queryFn: () => tasksService.listTaskCode(taskId, companyId),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['task-code', taskId] })
  const add = useMutation({
    mutationFn: () => tasksService.addTaskCode(taskId, { companyId, url: url.trim() }),
    onSuccess: () => { setUrl(''); refresh() },
    onError: (e) => toast.error((e as Error).message),
  })
  const drop = useMutation({
    mutationFn: (id: string) => tasksService.deleteTaskCode(taskId, id, companyId),
    onSuccess: refresh,
    onError: (e) => toast.error((e as Error).message),
  })

  const rows = q.data?.code ?? []
  return (
    <Section title="Код">
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={row.id} className="flex items-center gap-2 text-xs">
            <span className="w-[92px] shrink-0 text-[11px] text-muted-foreground">
              {CODE_KIND_LABEL[row.kind] ?? 'ссылка'}
            </span>
            <a href={row.url} target="_blank" rel="noreferrer"
              className="truncate font-mono text-primary hover:underline">
              {row.title}
            </a>
            {row.repo && (
              <span className="truncate text-[11px] text-muted-foreground">{row.repo}</span>
            )}
            {live && (
              <button type="button" aria-label={`Отвязать ${row.title}`}
                className="ml-auto shrink-0 text-muted-foreground hover:text-foreground"
                onClick={() => drop.mutate(row.id)}>
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
        {rows.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Ссылок на код нет. Вставьте адрес ветки, коммита или запроса на слияние.
          </p>
        )}
      </div>
      {live && (
        <div className="mt-2 flex gap-2">
          <Input value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/…/commit/a1b2c3d"
            className="h-8 flex-1 text-xs"
            onKeyDown={(e) => { if (e.key === 'Enter' && url.trim()) add.mutate() }} />
          <Button size="sm" className="h-8" disabled={!url.trim() || add.isPending}
            onClick={() => add.mutate()}>Привязать</Button>
        </div>
      )}
    </Section>
  )
}

const CODE_KIND_LABEL: Record<string, string> = {
  branch: 'ветка', commit: 'коммит', pr: 'слияние', other: 'ссылка',
}


function Links({ task, companyId, live, onChanged, onOpenOther }: {
  task: LoadedTask; companyId: string; live: boolean
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
  // Подзадачи — ветвление работы, остальные связи — её окружение.
  const kids = task.links.filter((l) => l.kind === 'subtask')
  const rest = task.links.filter((l) => l.kind !== 'subtask')

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
      {kids.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
            <span>Подзадачи</span>
            <span>{kids.filter((k) => k.status !== 'open').length} из {kids.length} закрыто</span>
          </div>
          <div className="space-y-0.5 border-l-2 border-border/60 pl-3">
            {kids.map((l) => (
              <div key={l.id} className="flex items-center gap-2 text-xs">
                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full',
                  l.status === 'open' ? 'bg-amber-500' : 'bg-emerald-500')} />
                <button type="button" onClick={() => onOpenOther?.(l.task_id)}
                  className={cn('truncate text-left hover:underline',
                    l.status !== 'open' && 'text-muted-foreground line-through')}>
                  <span className="font-medium">№{l.number}</span> {l.title}
                </button>
                {live && (
                  <Button variant="ghost" size="sm" className="ml-auto h-6 px-1.5"
                    aria-label="Снять связь" onClick={() => remove.mutate(l.id)}>
                    <Trash2 className="h-3 w-3" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1">
        {rest.map((l) => (
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
          <p className="text-xs text-muted-foreground">
            Связей нет. Крупную работу удобно разбить на подзадачи — они появятся
            здесь деревом, а прогресс будет виден в списке.
          </p>
        )}
      </div>
    </Section>
  )
}

/* ── Время: план и факт ──────────────────────────────────────────────── */

function TimePanel({ task, companyId, live, onChanged, onEstimate }: {
  task: LoadedTask; companyId: string; live: boolean
  onChanged: () => void; onEstimate: (v: string) => void
}) {
  const [dur, setDur] = useState('')
  const [what, setWhat] = useState('')
  const [estimate, setEstimateText] = useState('')
  const [editEstimate, setEditEstimate] = useState(false)

  const add = useMutation({
    mutationFn: () => tasksService.addWorkItem(task.id, {
      companyId, duration: dur.trim(), description: what.trim() || undefined,
    }),
    onSuccess: () => { setDur(''); setWhat(''); onChanged() },
    onError: (e) => toast.error((e as Error).message),
  })
  const drop = useMutation({
    mutationFn: (id: string) => tasksService.deleteWorkItem(task.id, id, companyId),
    onSuccess: onChanged,
    onError: (e) => toast.error((e as Error).message),
  })

  const time = task.time
  // Перерасход показываем словами и тоном: «плана 4 ч, потрачено 6 ч» — это
  // повод для разговора, а не для молчаливой красной цифры.
  const over = time.estimate != null && time.spent > time.estimate

  return (
    <Section title="Время" action={live && !editEstimate && (
      <button type="button"
        onClick={() => { setEstimateText(time.estimate_text.replace(' ', '')); setEditEstimate(true) }}
        className="text-[11px] text-muted-foreground hover:text-foreground">
        {time.estimate == null ? 'поставить оценку' : 'изменить оценку'}
      </button>
    )}>
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {editEstimate ? (
          <span className="flex items-center gap-1">
            <Input value={estimate} onChange={(e) => setEstimateText(e.target.value)}
              autoFocus placeholder="4ч" className="h-7 w-[90px] text-xs"
              onKeyDown={(e) => {
                if (e.key === 'Enter') { onEstimate(estimate); setEditEstimate(false) }
                if (e.key === 'Escape') setEditEstimate(false)
              }} />
            <Button size="sm" className="h-7"
              onClick={() => { onEstimate(estimate); setEditEstimate(false) }}>ок</Button>
            <Button size="sm" variant="ghost" className="h-7"
              onClick={() => { onEstimate(''); setEditEstimate(false) }}>снять</Button>
          </span>
        ) : (
          <span className="text-muted-foreground">
            оценка: <span className="text-foreground">{time.estimate_text}</span>
          </span>
        )}
        <span className="text-muted-foreground">
          потрачено: <span className={cn('font-medium',
            over ? 'text-amber-600 dark:text-amber-400' : 'text-foreground')}>
            {time.spent_text}
          </span>
        </span>
        {over && (
          <span className="text-[11px] text-amber-600 dark:text-amber-400">
            больше оценки на {Math.round((time.spent - (time.estimate ?? 0)) / 60 * 10) / 10} ч
          </span>
        )}
      </div>

      {task.work_items.length > 0 && (
        <div className="mt-2 space-y-1">
          {task.work_items.map((w) => (
            <div key={w.id} className="flex items-center gap-2 text-xs">
              <Clock className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="w-[92px] shrink-0 font-medium">{w.duration}</span>
              <span className="shrink-0 text-muted-foreground">
                {new Date(w.work_date).toLocaleDateString('ru-RU')}
              </span>
              <span className="truncate">{w.user}{w.description ? ` · ${w.description}` : ''}</span>
              <Button variant="ghost" size="sm" className="ml-auto h-6 px-1.5"
                aria-label="Убрать запись" onClick={() => drop.mutate(w.id)}>
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {live && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Input value={dur} onChange={(e) => setDur(e.target.value)}
            placeholder="2ч 30м" className="h-7 w-[110px] text-xs"
            onKeyDown={(e) => { if (e.key === 'Enter' && dur.trim()) add.mutate() }} />
          <Input value={what} onChange={(e) => setWhat(e.target.value)}
            placeholder="что делали" maxLength={500} className="h-7 flex-1 text-xs"
            onKeyDown={(e) => { if (e.key === 'Enter' && dur.trim()) add.mutate() }} />
          <Button size="sm" variant="outline" className="h-7"
            disabled={!dur.trim() || add.isPending} onClick={() => add.mutate()}>
            {add.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Записать время'}
          </Button>
        </div>
      )}
    </Section>
  )
}

/* ── Внешние участники: разговор каналом ─────────────────────────────── */

function External({ task, companyId, live, onChanged }: {
  task: LoadedTask; companyId: string; live: boolean; onChanged: () => void
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
  task: LoadedTask; companyId: string; live: boolean; onChanged: () => void
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


export default TaskCard
