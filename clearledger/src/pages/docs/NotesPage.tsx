/**
 * Записная книжка: то, что человек завёл сам себе.
 *
 * Отдельной сущности «заметка» нет и не заводится — это то же поручение с
 * кругом «только я». Правило, которое можно объяснить вслух: **без срока —
 * заметка, со сроком — дело**. Оттого переход между ними и есть самое частое
 * действие («это надо сделать до пятницы»), а не перенос из одного списка в
 * другой.
 *
 * Подача другая, чем в реестре, и намеренно: у заметки видно текст, а не
 * стадию и исполнителя, — она для чтения, а не для отслеживания. Из заметки
 * поднимается рабочее теми же ручками, что и везде: поставить срок, отдать
 * компании.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Bell, CalendarClock, Loader2, Lock, NotebookPen, Send } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import * as tasksService from '@/services/tasksService'
import * as workService from '@/services/workService'
import type { SpaceTask } from '@/services/tasksService'
import { dtT } from '@/components/tasks/taskWords'
import { cn } from '@/lib/utils'

/** Локальное «сейчас + N часов» для поля datetime-local: значение по умолчанию. */
const localNow = (plusHours: number) => {
  const d = new Date(Date.now() + plusHours * 3600_000)
  d.setMinutes(0, 0, 0)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

export function NotesPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const companyId = company?.id ?? ''
  const [text, setText] = useState('')

  const q = useQuery({
    queryKey: ['notes', companyId],
    queryFn: () => tasksService.listTasks(companyId, 'all', {
      visibility: 'personal', sort: '-updated', limit: 200,
    }),
    enabled: !!companyId,
  })

  const refresh = () => { void qc.invalidateQueries({ queryKey: ['notes', companyId] }) }

  const add = useMutation({
    mutationFn: () => {
      // Первая строка — заголовок, остальное — текст: в записной книжке пишут
      // сплошняком, и разводить «название» и «описание» двумя полями значит
      // требовать от человека решения, которого он не принимал.
      const [head, ...rest] = text.trim().split('\n')
      return tasksService.createTask({
        companyId, title: head.slice(0, 300),
        description: rest.join('\n').trim() || undefined,
        visibility: 'personal',
      })
    },
    onSuccess: () => { setText(''); refresh() },
    onError: (e: Error) => toast.error(e.message || 'Запись не сохранилась'),
  })

  if (!companyId) return null

  const rows = q.data?.tasks ?? []
  const заметки = rows.filter((t) => !t.due_at && t.status !== 'done')
  const дела = rows.filter((t) => t.due_at && t.status !== 'done')
  const сделано = rows.filter((t) => t.status === 'done')
  const open = (id: string) => navigate(`/tasks/${id}`)

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-3xl flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <NotebookPen className="h-4.5 w-4.5 text-primary" />Записная книжка
        </h1>
        <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Lock className="h-3 w-3" />
          Видите только вы: записи не попадают ни в реестр компании, ни к администратору
        </p>
      </header>

      <div className="rounded-lg border border-border bg-card p-3">
        <Textarea value={text} onChange={(e) => setText(e.target.value)}
          rows={2} placeholder="Что записать? Первая строка станет заголовком…"
          className="resize-none border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && text.trim()) {
              e.preventDefault()
              add.mutate()
            }
          }} />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">Ctrl+Enter — записать</span>
          <Button size="sm" disabled={!text.trim() || add.isPending}
            onClick={() => add.mutate()}>
            {add.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Записать
          </Button>
        </div>
      </div>

      {q.isError && (
        <QueryError message={(q.error as Error)?.message}
          onRetry={() => { void q.refetch() }} />
      )}

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto">
        {q.isLoading ? (
          <p className="text-sm text-muted-foreground">Загрузка…</p>
        ) : rows.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            Пока пусто. Запишите первое — решить, дело это или мысль, можно потом.
          </p>
        ) : (
          <>
            <Section title="Записи" hint="без срока — просто помню" rows={заметки}
              companyId={companyId} onChanged={refresh} onOpen={open} />
            <Section title="Дела" hint="со сроком — надо сделать" rows={дела}
              companyId={companyId} onChanged={refresh} onOpen={open} />
            {сделано.length > 0 && (
              <Section title="Сделано" hint="закрытое" rows={сделано.slice(0, 20)}
                companyId={companyId} onChanged={refresh} onOpen={open} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Section({ title, hint, rows, companyId, onChanged, onOpen }: {
  title: string; hint: string; rows: SpaceTask[]
  companyId: string; onChanged: () => void; onOpen: (id: string) => void
}) {
  if (rows.length === 0) return null
  return (
    <section>
      <h2 className="mb-1.5 flex items-baseline gap-2 text-sm font-medium text-foreground">
        {title}
        <span className="text-xs font-normal text-muted-foreground">{hint} · {rows.length}</span>
      </h2>
      <div className="space-y-2">
        {rows.map((t) => (
          <NoteRow key={t.id} task={t} companyId={companyId}
            onChanged={onChanged} onOpen={() => onOpen(t.id)} />
        ))}
      </div>
    </section>
  )
}

function NoteRow({ task, companyId, onChanged, onOpen }: {
  task: SpaceTask; companyId: string; onChanged: () => void; onOpen: () => void
}) {
  const [editing, setEditing] = useState<'due' | 'remind' | null>(null)
  const [value, setValue] = useState('')

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

  const done = task.status === 'done'
  return (
    <article className={cn('rounded-lg border border-border bg-card px-3 py-2.5',
      done && 'opacity-60')}>
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={done} className="mt-1 h-3.5 w-3.5 shrink-0"
          aria-label={done ? 'Вернуть в работу' : 'Отметить сделанным'}
          onChange={() => act.mutate({ companyId, status: done ? 'open' : 'done' })} />
        <button onClick={onOpen} className="min-w-0 flex-1 text-left">
          <p className={cn('text-sm text-foreground', done && 'line-through')}>{task.title}</p>
          {task.preview && (
            <p className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">
              {task.preview}
            </p>
          )}
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 pl-6 text-xs">
        {task.due_at && (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <CalendarClock className="h-3 w-3" />{dtT(task.due_at)}
          </span>
        )}
        {editing ? (
          <span className="inline-flex items-center gap-1.5">
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
