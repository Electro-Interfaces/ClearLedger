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
import {
  keepPreviousData, useMutation, useQuery, useQueryClient,
} from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Bell, CalendarClock, FileText, History, ImageOff, Link as LinkIcon,
  ListChecks, Loader2, Lock, Maximize2, NotebookPen, Paperclip, Pin,
  Search, Send, UserPlus, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SearchPicker } from '@/components/tasks/SearchPicker'
import { NewDocDialog } from '@/components/docs/NewDocDialog'
import * as tasksService from '@/services/tasksService'
import * as docsService from '@/services/docsService'
import * as workService from '@/services/workService'
import type { SpaceTask, TaskFile } from '@/services/tasksService'
import { dtT } from '@/components/tasks/taskWords'
import { humanSize, openAuthAttachment, useAuthBlob } from '@/lib/authFiles'
import { nextEvening, nextMorning, toItems, toText } from '@/lib/noteText'
import { cn } from '@/lib/utils'

/** Локальное «сейчас + N часов» для поля datetime-local: значение по умолчанию. */
const localNow = (plusHours: number) => {
  const d = new Date(Date.now() + plusHours * 3600_000)
  d.setMinutes(0, 0, 0)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

/** Что сейчас открыто в строке. Одно за раз: два раскрытых поля в строке
 *  списка превращают её в форму. */
type Режим = 'due' | 'remind' | 'assign' | 'link' | 'revisions' | null

type ОперацияПункта =
  | { kind: 'add'; text: string }
  | { kind: 'toggle'; id: string; done: boolean }
  | { kind: 'remove'; id: string }

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

  // Поиск спрашивает СЕРВЕР. Клиентский фильтр видел только заголовок и первые
  // 200 символов описания у 200 загруженных строк — всё, что человек написал
  // ниже, не находилось, и книжка тихо врала: «не нашлось» означало «не искали».
  const слово = поиск.trim()
  const q = useQuery({
    queryKey: ['notes', companyId, слово],
    queryFn: () => tasksService.listTasks(companyId, 'all', {
      visibility: 'personal', sort: '-created', limit: 200,
      q: слово || undefined,
    }),
    enabled: !!companyId,
    // Прежняя выдача остаётся на экране, пока идёт запрос за новой: без этого
    // список моргает пустотой на каждой букве.
    placeholderData: keepPreviousData,
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
    const видно = rows.filter((t) => {
      if (отбор === 'done') return t.status === 'done'
      if (отбор === 'due') return t.due_at && t.status !== 'done'
      if (отбор === 'overdue') return t.overdue && t.status !== 'done'
      // «Все» — открытое плюс закрытое за последние сутки: отметив галочку,
      // человек не должен видеть, как запись исчезает у него из-под руки.
      return t.status !== 'done' || закрытоНедавно(t.closed_at)
    })

    // Закреплённое — отдельной группой сверху, а не «сегодня, но повыше».
    // Человек закрепляет запись именно затем, чтобы она не уезжала вниз вместе
    // с днём, в который её завели. Закрепление — та же личная звезда, что в
    // раскладке работы (`personal_marks.starred`): второй механизм «важного» у
    // одного человека означал бы два разных ответа на один вопрос.
    const закреплено = видно.filter((t) => t.mark?.starred)
    const обычные = видно.filter((t) => !t.mark?.starred)

    const собрано: { key: string; label: string; rows: SpaceTask[] }[] = []
    if (закреплено.length) {
      собрано.push({ key: 'pinned', label: 'Закреплённые', rows: закреплено })
    }
    for (const t of обычные) {
      const iso = t.created_at ?? t.updated_at
      if (!iso) continue
      const key = деньКлюч(iso)
      const последний = собрано[собрано.length - 1]
      if (последний?.key === key && последний.key !== 'pinned') последний.rows.push(t)
      else собрано.push({ key, label: имяДня(iso), rows: [t] })
    }
    return собрано
  }, [rows, отбор])

  if (!companyId) return null

  // Пустая книжка и «по запросу ничего» — разные ответы, и путать их нельзя:
  // человек, ищущий слово, решит, что потерял все записи.
  const пусто = rows.length === 0 && !слово
  const ничегоНеНайдено = !пусто && дни.length === 0

  return (
    <div className="flex h-full min-h-0 w-full max-w-5xl flex-col gap-4 px-4 py-4">
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
        {/* Курсор стоит в поле сразу: записную книжку открывают, чтобы записать,
            а не чтобы сначала прицелиться мышью. */}
        <Textarea value={text} onChange={(e) => setText(e.target.value)} autoFocus
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
            <Button variant="ghost" size="sm" className="h-8 px-2 text-xs"
              onClick={() => fileRef.current?.click()}>
              <Paperclip className="mr-1 h-3.5 w-3.5" />Файл
            </Button>
            <span className="text-xs text-muted-foreground">
              Скриншот — Ctrl+V, файл — перетащите сюда
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-xs text-muted-foreground sm:inline">
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
          <p className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted-foreground">
            Пока пусто. Запишите первое — решить, дело это или мысль, можно потом:
            запись со сроком становится делом, без срока остаётся заметкой.
          </p>
        ) : ничегоНеНайдено ? (
          <p className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted-foreground">
            {поиск.trim() ? `По запросу «${поиск.trim()}» ничего нет` : 'В этом отборе пусто'}
          </p>
        ) : (
          <div className="space-y-4">
            {дни.map((день) => (
              <section key={день.key}>
                <h2 className="sticky top-0 z-10 -mx-1 bg-background/95 px-1 pb-1 pt-0.5 text-xs font-medium uppercase tracking-wide text-muted-foreground backdrop-blur">
                  {день.label}
                </h2>
                <div className="divide-y divide-border/70">
                  {день.rows.map((t) => (
                    <NoteRow key={t.id} task={t} companyId={companyId}
                      onChanged={refresh}
                      // Прежний адрес `/tasks/<id>` ведёт на редирект снятого
                      // раздела, и номер записи по дороге теряется: карточка
                      // открывалась не та, а список поручений.
                      onOpen={() => navigate(`/docs/company?view=errands&task=${t.id}`)} />
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

/**
 * Строка записи: сама запись и все её выходы в рабочий контур.
 *
 * Записная книжка — вспомогательный контур, и главное в ней не то, что запись
 * можно завести, а то, что её можно ОТДАТЬ: поставить срок, поручить, превратить
 * в документ, связать с чем-то. Без этих выходов книжка становится кладбищем
 * мыслей рядом с работой, а не её преддверием.
 *
 * Правка идёт на месте и сохраняется сама. Пара к автосохранению — редакции:
 * сохранять молча и не давать вернуться значит однажды потерять абзац навсегда.
 */
function NoteRow({ task, companyId, onChanged, onOpen }: {
  task: SpaceTask; companyId: string; onChanged: () => void; onOpen: () => void
}) {
  const navigate = useNavigate()
  const [editing, setEditing] = useState<Режим>(null)
  const [value, setValue] = useState('')
  const [draft, setDraft] = useState<string | null>(null)
  const [newItem, setNewItem] = useState('')
  const [docOpen, setDocOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const сохранение = useRef<ReturnType<typeof setTimeout> | null>(null)

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
  // Закрепление — та же личная звезда, что в раскладке работы. Второй механизм
  // «важного» у одного человека означал бы два разных ответа на один вопрос.
  const pin = useMutation({
    mutationFn: () => workService.place(companyId, `task:${task.id}`,
      { starred: !task.mark?.starred }),
    onSuccess: onChanged,
    onError: (e: Error) => toast.error(e.message || 'Не закрепилось'),
  })
  const item = useMutation({
    mutationFn: async (op: ОперацияПункта) => {
      if (op.kind === 'add') return tasksService.addChecklistItem(task.id, companyId, op.text)
      if (op.kind === 'toggle') {
        return tasksService.updateChecklistItem(task.id, op.id, { companyId, done: op.done })
      }
      return tasksService.deleteChecklistItem(task.id, op.id, companyId)
    },
    onSuccess: () => { setNewItem(''); onChanged() },
    onError: (e: Error) => toast.error(e.message || 'Пункт не сохранился'),
  })

  const пункты = task.checklist_items ?? []

  /** Текст ↔ список. Обе стороны обратимы: превратив запись в список и передумав,
   *  человек обязан получить свой текст назад, а не пустое поле. */
  const превращение = useMutation({
    mutationFn: async () => {
      if (пункты.length) {
        await tasksService.taskAction(task.id, {
          companyId,
          description: toText(пункты, task.description ?? task.preview ?? ''),
        })
        for (const i of пункты) {
          await tasksService.deleteChecklistItem(task.id, i.id, companyId)
        }
        return
      }
      const строки = toItems(task.description ?? task.preview ?? '')
      if (!строки.length) throw new Error('В записи нет строк, из которых вышел бы список')
      for (const s of строки) await tasksService.addChecklistItem(task.id, companyId, s)
      await tasksService.taskAction(task.id, { companyId, description: '' })
    },
    onSuccess: onChanged,
    onError: (e: Error) => toast.error(e.message || 'Не превратилось'),
  })

  const people = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: editing === 'assign', staleTime: 5 * 60 * 1000,
  })
  const соседи = useQuery({
    queryKey: ['notes-neighbours', companyId],
    queryFn: () => tasksService.listTasks(companyId, 'all',
      { visibility: 'personal', sort: '-created', limit: 100 }),
    enabled: editing === 'link', staleTime: 60 * 1000,
  })
  const revisions = useQuery({
    queryKey: ['note-revisions', task.id],
    queryFn: () => tasksService.noteRevisions(task.id, companyId),
    enabled: editing === 'revisions',
  })
  const kinds = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listDocKinds(companyId),
    enabled: docOpen,
  })

  const link = useMutation({
    mutationFn: (id: string) => tasksService.addTaskLink(task.id,
      { companyId, relatedTaskId: id, kind: 'relates' }),
    onSuccess: () => { setEditing(null); toast.success('Связал'); onChanged() },
    onError: (e: Error) => toast.error(e.message || 'Не связалось'),
  })

  /** Автосохранение правки: гасим таймер и шлём один раз. Записную книжку
   *  закрывают на полуслове, и «не нажал сохранить» здесь недопустимо. */
  const отложенноеСохранение = (текст: string) => {
    setDraft(текст)
    if (сохранение.current) clearTimeout(сохранение.current)
    сохранение.current = setTimeout(() => {
      const [head, ...rest] = текст.trim().split('\n')
      act.mutate({
        companyId,
        title: head.slice(0, 300) || 'Без названия',
        description: rest.join('\n').trim(),
      })
    }, 1200)
  }

  const done = task.status === 'done'
  const files = task.attachments ?? []
  const картинки = files.filter(изображение)
  const документы = files.filter((f) => !изображение(f))
  const закреплено = !!task.mark?.starred
  const текстЗаписи = [task.title, task.description ?? task.preview ?? '']
    .filter(Boolean).join('\n')

  return (
    <article className={cn('group py-2.5', done && 'opacity-55')}>
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={done} className="mt-1 h-3.5 w-3.5 shrink-0"
          aria-label={done ? 'Вернуть в работу' : 'Отметить сделанным'}
          onChange={() => act.mutate({ companyId, status: done ? 'open' : 'done' })} />
        {draft !== null ? (
          <Textarea value={draft} autoFocus rows={Math.min(12, draft.split('\n').length + 1)}
            onChange={(e) => отложенноеСохранение(e.target.value)}
            onBlur={() => {
              if (сохранение.current) clearTimeout(сохранение.current)
              const [head, ...rest] = draft.trim().split('\n')
              act.mutate({
                companyId, title: head.slice(0, 300) || 'Без названия',
                description: rest.join('\n').trim(),
              })
              setDraft(null)
            }}
            className="min-w-0 flex-1 resize-none text-sm" />
        ) : (
          <button onClick={() => setDraft(текстЗаписи)}
            className="min-w-0 flex-1 text-left">
            <p className={cn('text-sm text-foreground', done && 'line-through')}>
              {task.title}
            </p>
            {!пункты.length && task.preview && (
              <p className="mt-0.5 line-clamp-4 whitespace-pre-wrap text-xs text-muted-foreground">
                {task.preview}
              </p>
            )}
          </button>
        )}
        {закреплено && (
          <Pin className="mt-0.5 h-3 w-3 shrink-0 fill-current text-amber-600 dark:text-amber-400"
            aria-label="закреплено" />
        )}
        {task.created_at && (
          <time className="shrink-0 text-xs tabular-nums text-muted-foreground"
            dateTime={task.created_at}>
            {время.format(new Date(task.created_at))}
          </time>
        )}
      </div>

      {пункты.length > 0 && (
        <ul className="mt-1.5 space-y-1 pl-6">
          {пункты.map((i) => (
            <li key={i.id} className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={i.done} className="mt-1 h-3.5 w-3.5 shrink-0"
                onChange={() => item.mutate({ kind: 'toggle', id: i.id, done: !i.done })} />
              <span className={cn('min-w-0 flex-1', i.done && 'text-muted-foreground line-through')}>
                {i.text}
              </span>
              <button onClick={() => item.mutate({ kind: 'remove', id: i.id })}
                className="shrink-0 text-muted-foreground/60 hover:text-foreground"
                aria-label="Убрать пункт">
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
          <li>
            <Input value={newItem} onChange={(e) => setNewItem(e.target.value)}
              placeholder="Ещё пункт…" className="h-7 text-sm"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newItem.trim()) {
                  item.mutate({ kind: 'add', text: newItem.trim() })
                }
              }} />
          </li>
        </ul>
      )}

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

        {editing === 'due' || editing === 'remind' ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            {editing === 'remind' && (
              // Быстрые ответы на вопрос «когда»: точное время выбирают редко,
              // а «вечером» и «завтра утром» — почти всегда.
              <>
                <Button size="sm" variant="outline" className="h-8 px-2 text-xs"
                  onClick={() => remind.mutate(nextEvening())}>Вечером</Button>
                <Button size="sm" variant="outline" className="h-8 px-2 text-xs"
                  onClick={() => remind.mutate(nextMorning())}>Завтра утром</Button>
              </>
            )}
            <Input type="datetime-local" value={value} autoFocus
              onChange={(e) => setValue(e.target.value)}
              className="h-8 w-[190px] text-xs" />
            <Button size="sm" className="h-8 px-2 text-xs" disabled={!value}
              onClick={() => (editing === 'due'
                ? act.mutate({ companyId, dueAt: new Date(value).toISOString() })
                : remind.mutate(value))}>
              Готово
            </Button>
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
              onClick={() => setEditing(null)}>Отмена</Button>
          </span>
        ) : editing === 'assign' ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <SearchPicker
              items={(people.data?.people ?? []).map((p) => ({
                id: p.id, name: p.name, party: p.partyType }))}
              value="" onChange={(v) => act.mutate(
                { companyId, visibility: 'company', assigneeId: v })}
              placeholder="Кому поручить" emptyLabel="Не назначен"
              searchPlaceholder="Фамилия или имя…" className="w-[210px]"
              loading={people.isLoading} />
            <span className="text-muted-foreground">
              запись станет поручением и уйдёт из книжки
            </span>
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
              onClick={() => setEditing(null)}>Отмена</Button>
          </span>
        ) : editing === 'link' ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <SearchPicker
              items={(соседи.data?.tasks ?? []).filter((n) => n.id !== task.id)
                .map((n) => ({ id: n.id, name: n.title }))}
              value="" onChange={(v) => link.mutate(v)}
              placeholder="С какой записью" searchPlaceholder="Слово из записи…"
              className="w-[240px]" loading={соседи.isLoading} />
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
              onClick={() => setEditing(null)}>Отмена</Button>
          </span>
        ) : editing === 'revisions' ? (
          <div className="w-full space-y-1">
            {revisions.isLoading && (
              <span className="text-muted-foreground">Смотрю редакции…</span>
            )}
            {revisions.data?.revisions.length === 0 && (
              <span className="text-muted-foreground">
                Прежних редакций нет — запись ещё не правили
              </span>
            )}
            {(revisions.data?.revisions ?? []).map((r) => (
              <button key={r.id}
                onClick={() => { setDraft(r.text); setEditing(null) }}
                className="block w-full rounded border border-border px-2 py-1 text-left hover:border-primary/50">
                <span className="text-muted-foreground">
                  {r.at ? dtT(r.at) : '—'}
                </span>
                <span className="ml-2 line-clamp-2 whitespace-pre-wrap">{r.text}</span>
              </button>
            ))}
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
              onClick={() => setEditing(null)}>Закрыть</Button>
          </div>
        ) : (
          <>
            <button onClick={() => pin.mutate()} disabled={pin.isPending}
              title={закреплено ? 'Открепить' : 'Закрепить наверху'}
              className={cn('inline-flex items-center gap-1 hover:text-foreground',
                закреплено ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
              <Pin className={cn('h-3 w-3', закреплено && 'fill-current')} />
              {закреплено ? 'Открепить' : 'Закрепить'}
            </button>
            <button onClick={() => { setValue(localNow(24)); setEditing('due') }}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <CalendarClock className="h-3 w-3" />{task.due_at ? 'Перенести' : 'Срок'}
            </button>
            <button onClick={() => { setValue(localNow(1)); setEditing('remind') }}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <Bell className="h-3 w-3" />Напомнить
            </button>
            <button onClick={() => превращение.mutate()} disabled={превращение.isPending}
              title={пункты.length
                ? 'Пункты снова станут строками текста'
                : 'Каждая строка станет пунктом списка'}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground disabled:opacity-50">
              <ListChecks className="h-3 w-3" />{пункты.length ? 'В текст' : 'В список'}
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

            {/* Выходы в рабочий контур — за одним пунктом. Каждый из них
                означает, что запись перестаёт быть личной, и такие действия не
                должны стоять в одном ряду с «приложить файл». */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
                  <Send className="h-3 w-3" />В работу
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                  Запись выходит из личного контура
                </DropdownMenuLabel>
                <DropdownMenuItem onClick={() => setEditing('assign')}>
                  <UserPlus className="mr-2 h-3.5 w-3.5" />Поручить…
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => act.mutate({ companyId, visibility: 'company' })}>
                  <Send className="mr-2 h-3.5 w-3.5" />Отдать компании без исполнителя
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setDocOpen(true)}>
                  <FileText className="mr-2 h-3.5 w-3.5" />Создать документ…
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => setEditing('link')}>
                  <LinkIcon className="mr-2 h-3.5 w-3.5" />Связать с записью…
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setEditing('revisions')}>
                  <History className="mr-2 h-3.5 w-3.5" />Прежние редакции
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onOpen}>
                  <Maximize2 className="mr-2 h-3.5 w-3.5" />Открыть карточкой
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
      </div>

      {docOpen && (
        <NewDocDialog companyId={companyId} kinds={kinds.data?.kinds ?? []}
          initialTitle={task.title}
          summary={task.description ?? task.preview ?? undefined}
          subjectRef={`task:${task.id}`}
          onClose={() => setDocOpen(false)}
          onCreated={(id) => { setDocOpen(false); onChanged(); navigate(`/docs?view=all&doc=${id}`) }} />
      )}
    </article>
  )
}


export default NotesPage
