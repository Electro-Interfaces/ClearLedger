/**
 * Записная книжка: то, что человек завёл сам себе.
 *
 * Отдельной сущности «заметка» нет и не заводится — это то же поручение с
 * кругом «только я». Правило, которое можно объяснить вслух: **без срока —
 * заметка, со сроком — дело**. Оттого переход между ними и есть самое частое
 * действие («это надо сделать до пятницы»), а не перенос из одного списка в
 * другой.
 *
 * Подача — лента по дням, а не реестр. Записную книжку человек ищет памятью о
 * времени («записал на той неделе»), а не по стадии и исполнителю; поэтому
 * заголовок дня несёт больше, чем любая колонка, а рамка вокруг каждой записи
 * только мешает читать. Прежняя раскладка делила записи на «без срока» и «со
 * сроком» двумя списками: поставив срок, человек терял запись из виду — она
 * молча уезжала во второй список.
 *
 * Скриншот здесь — содержание, а не приложение к нему: «вот это письмо», «вот
 * эта ошибка». Поэтому вставка из буфера, перетаскивание и скрепка есть прямо
 * в поле записи, а изображения видны миниатюрами в строке.
 */
import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Bell, CalendarClock, ImageOff, Loader2, Lock, NotebookPen, Paperclip,
  Search, Send, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import * as workService from '@/services/workService'
import type { SpaceTask, TaskFile } from '@/services/tasksService'
import { dtT } from '@/components/tasks/taskWords'
import { humanSize, openAuthAttachment, useAuthBlob } from '@/lib/authFiles'
import { cn } from '@/lib/utils'

/** Локальное «сейчас + N часов» для поля datetime-local: значение по умолчанию. */
const localNow = (plusHours: number) => {
  const d = new Date(Date.now() + plusHours * 3600_000)
  d.setMinutes(0, 0, 0)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

const время = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' })
const деньМесяц = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' })
const деньМесяцГод = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric', month: 'long', year: 'numeric',
})

/** Ключ дня в местном времени: по нему записи собираются в группу. */
const деньКлюч = (iso: string) => {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

/** Как день называется вслух. Ближние дни — словом: так их и вспоминают. */
function имяДня(iso: string): string {
  const d = new Date(iso)
  const сейчас = new Date()
  const сутки = 86_400_000
  const начало = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const разница = Math.round((начало(сейчас) - начало(d)) / сутки)
  if (разница === 0) return 'Сегодня'
  if (разница === 1) return 'Вчера'
  return d.getFullYear() === сейчас.getFullYear() ? деньМесяц.format(d) : деньМесяцГод.format(d)
}

const изображение = (f: TaskFile) => f.mime_type?.startsWith('image/')

/** Закрыто в последние сутки. Отдельной функцией, а не строкой в отборе: время
 *  берётся на момент отбора, и лента пересобирается при каждом обновлении
 *  списка — иначе отметив галочку, человек видит, как запись пропадает у него
 *  из-под руки. */
const закрытоНедавно = (iso: string | null) =>
  Boolean(iso && new Date(iso).getTime() > Date.now() - 86_400_000)

type Отбор = 'all' | 'due' | 'overdue' | 'done'

export function NotesPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const companyId = company?.id ?? ''
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [поиск, setПоиск] = useState('')
  const [отбор, setОтбор] = useState<Отбор>('all')
  const fileRef = useRef<HTMLInputElement>(null)

  const q = useQuery({
    queryKey: ['notes', companyId],
    queryFn: () => tasksService.listTasks(companyId, 'all', {
      visibility: 'personal', sort: '-created', limit: 200,
    }),
    enabled: !!companyId,
  })

  const refresh = () => { void qc.invalidateQueries({ queryKey: ['notes', companyId] }) }
  const addFiles = (list: FileList | File[] | null) => {
    const picked = Array.from(list ?? [])
    if (picked.length) setFiles((f) => [...f, ...picked])
  }

  const add = useMutation({
    mutationFn: async () => {
      // Первая строка — заголовок, остальное — текст: в записной книжке пишут
      // сплошняком, и разводить «название» и «описание» двумя полями значит
      // требовать от человека решения, которого он не принимал.
      const [head, ...rest] = text.trim().split('\n')
      const note = await tasksService.createTask({
        companyId, title: head.slice(0, 300) || 'Без названия',
        description: rest.join('\n').trim() || undefined,
        visibility: 'personal',
      })
      for (const file of files) {
        await tasksService.uploadTaskFile(note.id, companyId, file)
          .catch(() => toast.warning(`Файл «${file.name}» не приложился`))
      }
      return note
    },
    onSuccess: () => { setText(''); setFiles([]); refresh() },
    onError: (e: Error) => toast.error(e.message || 'Запись не сохранилась'),
  })

  const rows = useMemo(() => q.data?.tasks ?? [], [q.data])
  const счёт = useMemo(() => ({
    due: rows.filter((t) => t.due_at && t.status !== 'done').length,
    overdue: rows.filter((t) => t.overdue && t.status !== 'done').length,
    done: rows.filter((t) => t.status === 'done').length,
  }), [rows])

  const дни = useMemo(() => {
    const слово = поиск.trim().toLowerCase()
    const видно = rows.filter((t) => {
      if (отбор === 'done') return t.status === 'done'
      if (отбор === 'due') return t.due_at && t.status !== 'done'
      if (отбор === 'overdue') return t.overdue && t.status !== 'done'
      // «Все» — открытое плюс закрытое за последние сутки: отметив галочку,
      // человек не должен видеть, как запись исчезает у него из-под руки.
      return t.status !== 'done' || закрытоНедавно(t.closed_at)
    }).filter((t) => !слово
      || t.title.toLowerCase().includes(слово)
      || (t.preview ?? '').toLowerCase().includes(слово))

    const собрано: { key: string; label: string; rows: SpaceTask[] }[] = []
    for (const t of видно) {
      const iso = t.created_at ?? t.updated_at
      if (!iso) continue
      const key = деньКлюч(iso)
      const последний = собрано[собрано.length - 1]
      if (последний?.key === key) последний.rows.push(t)
      else собрано.push({ key, label: имяДня(iso), rows: [t] })
    }
    return собрано
  }, [rows, отбор, поиск])

  if (!companyId) return null

  const пусто = rows.length === 0
  const ничегоНеНайдено = !пусто && дни.length === 0

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-3xl flex-col gap-4 px-4 py-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <NotebookPen className="h-4.5 w-4.5 text-primary" />Записная книжка
          </h1>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Lock className="h-3 w-3" />
            Видите только вы: записи не попадают ни в реестр компании, ни к администратору
          </p>
        </div>
        {!пусто && (
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
              placeholder="Найти в записях" aria-label="Найти в записях"
              className="h-8 w-[210px] pl-7 text-sm" />
          </div>
        )}
      </header>

      <div
        className={cn('rounded-lg border bg-card p-3 transition-colors',
          dragOver ? 'border-primary bg-primary/[0.04]' : 'border-border')}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files)
        }}>
        <Textarea value={text} onChange={(e) => setText(e.target.value)}
          rows={2} placeholder="Что записать? Первая строка станет заголовком…"
          className="resize-none border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0"
          // Вставка изображения из буфера: скриншот попадает в запись без
          // промежуточного «сохранить на диск» — иначе заметку просто не заведут.
          onPaste={(e) => {
            const imgs = Array.from(e.clipboardData.files).filter(
              (f) => f.type.startsWith('image/'))
            if (imgs.length) {
              e.preventDefault()
              addFiles(imgs)
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && (text.trim() || files.length)) {
              e.preventDefault()
              add.mutate()
            }
          }} />

        {files.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`}
                className="flex items-center gap-1.5 rounded border border-border bg-muted/40 py-1 pl-1.5 pr-1 text-xs">
                {f.type.startsWith('image/')
                  ? <LocalThumb file={f} />
                  : <Paperclip className="h-3 w-3 shrink-0 text-muted-foreground" />}
                <span className="max-w-[160px] truncate">{f.name}</span>
                <span className="shrink-0 text-muted-foreground">{humanSize(f.size)}</span>
                <button type="button" aria-label={`Убрать «${f.name}»`}
                  onClick={() => setFiles((list) => list.filter((_, k) => k !== i))}
                  className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground">
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <input ref={fileRef} type="file" multiple className="hidden"
              onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
              onClick={() => fileRef.current?.click()}>
              <Paperclip className="mr-1 h-3.5 w-3.5" />Файл
            </Button>
            <span className="text-[11px] text-muted-foreground">
              Скриншот — Ctrl+V, файл — перетащите сюда
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-[11px] text-muted-foreground sm:inline">
              Ctrl+Enter — записать
            </span>
            <Button size="sm" disabled={(!text.trim() && !files.length) || add.isPending}
              onClick={() => add.mutate()}>
              {add.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Записать
            </Button>
          </div>
        </div>
      </div>

      {q.isError && (
        <QueryError message={(q.error as Error)?.message}
          onRetry={() => { void q.refetch() }} />
      )}

      {!пусто && (
        <div className="flex flex-wrap items-center gap-1">
          <FilterChip активна={отбор === 'all'} onClick={() => setОтбор('all')}>Все</FilterChip>
          {счёт.due > 0 && (
            <FilterChip активна={отбор === 'due'} onClick={() => setОтбор('due')}>
              Со сроком {счёт.due}
            </FilterChip>
          )}
          {счёт.overdue > 0 && (
            <FilterChip активна={отбор === 'overdue'} onClick={() => setОтбор('overdue')}
              тон="alert">
              Просрочено {счёт.overdue}
            </FilterChip>
          )}
          {счёт.done > 0 && (
            <FilterChip активна={отбор === 'done'} onClick={() => setОтбор('done')}>
              Сделанное {счёт.done}
            </FilterChip>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {q.isLoading ? (
          <div className="space-y-2" aria-label="Загружаю записи">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-14 animate-pulse rounded-lg bg-muted/60" />
            ))}
          </div>
        ) : пусто ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            Пока пусто. Запишите первое — решить, дело это или мысль, можно потом:
            запись со сроком становится делом, без срока остаётся заметкой.
          </p>
        ) : ничегоНеНайдено ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            {поиск.trim() ? `По запросу «${поиск.trim()}» ничего нет` : 'В этом отборе пусто'}
          </p>
        ) : (
          <div className="space-y-4">
            {дни.map((день) => (
              <section key={день.key}>
                <h2 className="sticky top-0 z-10 -mx-1 bg-background/95 px-1 pb-1 pt-0.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground backdrop-blur">
                  {день.label}
                </h2>
                <div className="divide-y divide-border/70">
                  {день.rows.map((t) => (
                    <NoteRow key={t.id} task={t} companyId={companyId}
                      onChanged={refresh} onOpen={() => navigate(`/tasks/${t.id}`)} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function FilterChip({ активна, тон, onClick, children }: {
  активна: boolean; тон?: 'alert'; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button type="button" onClick={onClick}
      aria-pressed={активна}
      className={cn('rounded-md px-2.5 py-1 text-xs transition-colors',
        активна
          ? 'bg-primary text-primary-foreground'
          : тон === 'alert'
            ? 'text-red-600 hover:bg-accent dark:text-red-400'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
      {children}
    </button>
  )
}

/** Thumb ещё не отправленного файла — из локального объекта, без сети. */
function LocalThumb({ file }: { file: File }) {
  const url = useMemo(() => URL.createObjectURL(file), [file])
  return <img src={url} alt="" className="h-5 w-5 shrink-0 rounded object-cover" />
}

/** Thumb приложенного изображения: файл закрыт JWT, прямой адрес не работает. */
function Thumb({ file, companyId }: { file: TaskFile; companyId: string }) {
  const path = tasksService.taskFileUrl(file.id, companyId)
  const { url, error } = useAuthBlob(path)
  return (
    <button type="button" title={file.file_name}
      onClick={() => { void openAuthAttachment(path).catch(() => toast.error('Файл не открылся')) }}
      className="h-16 w-24 overflow-hidden rounded border border-border bg-muted transition-opacity hover:opacity-90">
      {error ? (
        <span className="flex h-full w-full items-center justify-center text-muted-foreground">
          <ImageOff className="h-4 w-4" />
        </span>
      ) : url ? (
        <img src={url} alt={file.file_name} className="h-full w-full object-cover" />
      ) : (
        <span className="flex h-full w-full items-center justify-center">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
        </span>
      )}
    </button>
  )
}

function NoteRow({ task, companyId, onChanged, onOpen }: {
  task: SpaceTask; companyId: string; onChanged: () => void; onOpen: () => void
}) {
  const [editing, setEditing] = useState<'due' | 'remind' | null>(null)
  const [value, setValue] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const act = useMutation({
    mutationFn: (data: Parameters<typeof tasksService.taskAction>[1]) =>
      tasksService.taskAction(task.id, data),
    onSuccess: () => { setEditing(null); onChanged() },
    onError: (e: Error) => toast.error(e.message || 'Не получилось'),
  })
  const remind = useMutation({
    mutationFn: (when: string) => workService.createReminder(companyId, {
      targetRef: `task:${task.id}`,
      remindAt: new Date(when).toISOString(),
      note: `Напоминание: ${task.title}`,
    }),
    onSuccess: () => { setEditing(null); toast.success('Напомню') },
    onError: (e: Error) => toast.error(e.message || 'Напоминание не поставилось'),
  })
  const attach = useMutation({
    mutationFn: (file: File) => tasksService.uploadTaskFile(task.id, companyId, file),
    onSuccess: onChanged,
    onError: (e: Error) => toast.error(e.message || 'Файл не приложился'),
  })

  const done = task.status === 'done'
  const files = task.attachments ?? []
  const картинки = files.filter(изображение)
  const документы = files.filter((f) => !изображение(f))

  return (
    <article className={cn('group py-2.5', done && 'opacity-55')}>
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={done} className="mt-1 h-3.5 w-3.5 shrink-0"
          aria-label={done ? 'Вернуть в работу' : 'Отметить сделанным'}
          onChange={() => act.mutate({ companyId, status: done ? 'open' : 'done' })} />
        <button onClick={onOpen} className="min-w-0 flex-1 text-left">
          <p className={cn('text-sm text-foreground', done && 'line-through')}>{task.title}</p>
          {task.preview && (
            <p className="mt-0.5 line-clamp-4 whitespace-pre-wrap text-xs text-muted-foreground">
              {task.preview}
            </p>
          )}
        </button>
        {task.created_at && (
          <time className="shrink-0 text-[11px] tabular-nums text-muted-foreground"
            dateTime={task.created_at}>
            {время.format(new Date(task.created_at))}
          </time>
        )}
      </div>

      {картинки.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5 pl-6">
          {картинки.map((f) => <Thumb key={f.id} file={f} companyId={companyId} />)}
        </div>
      )}
      {документы.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-6">
          {документы.map((f) => (
            <li key={f.id}>
              <button type="button"
                onClick={() => {
                  void openAuthAttachment(tasksService.taskFileUrl(f.id, companyId))
                    .catch(() => toast.error('Файл не открылся'))
                }}
                className="flex items-center gap-1.5 text-xs text-primary hover:underline">
                <Paperclip className="h-3 w-3 shrink-0" />
                <span className="max-w-[280px] truncate">{f.file_name}</span>
                <span className="shrink-0 text-muted-foreground">{humanSize(f.size)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 pl-6 text-xs">
        {task.due_at && (
          <span className={cn('inline-flex items-center gap-1',
            task.overdue && !done ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
            <CalendarClock className="h-3 w-3" />
            {task.overdue && !done ? 'просрочено · ' : ''}{dtT(task.due_at)}
          </span>
        )}
        {editing ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <Input type="datetime-local" value={value} autoFocus
              onChange={(e) => setValue(e.target.value)}
              className="h-7 w-[190px] text-xs" />
            <Button size="sm" className="h-7 px-2 text-xs" disabled={!value}
              onClick={() => (editing === 'due'
                ? act.mutate({ companyId, dueAt: new Date(value).toISOString() })
                : remind.mutate(value))}>
              Готово
            </Button>
            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
              onClick={() => setEditing(null)}>Отмена</Button>
          </span>
        ) : (
          <>
            <button onClick={() => { setValue(localNow(24)); setEditing('due') }}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <CalendarClock className="h-3 w-3" />{task.due_at ? 'Перенести' : 'Срок'}
            </button>
            <button onClick={() => { setValue(localNow(1)); setEditing('remind') }}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <Bell className="h-3 w-3" />Напомнить
            </button>
            <input ref={fileRef} type="file" className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) attach.mutate(f)
                e.target.value = ''
              }} />
            <button onClick={() => fileRef.current?.click()} disabled={attach.isPending}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground disabled:opacity-50">
              {attach.isPending
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : <Paperclip className="h-3 w-3" />}
              Файл
            </button>
            <button onClick={() => act.mutate({ companyId, visibility: 'company' })}
              title="Запись становится обычным поручением: её увидит компания, и ей можно назначить исполнителя"
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <Send className="h-3 w-3" />В работу
            </button>
          </>
        )}
      </div>
    </article>
  )
}

export default NotesPage
