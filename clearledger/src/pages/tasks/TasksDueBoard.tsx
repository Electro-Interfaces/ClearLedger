/**
 * Доска личной работы: колонки — сроки, а не стадии маршрута.
 *
 * На доске компании колонки это этапы выбранного типа. Для «моей работы» такая
 * доска бесполезна: у меня одновременно поручение, согласование и инцидент, и
 * маршруты у них разные. А вопрос ко «своей» доске другой — не «на каком шаге
 * работа», а «что сегодня, что на неделе, что можно отложить».
 *
 * Поэтому колонки здесь — сроки, и перенос карточки меняет срок. Это и есть
 * планирование: перетащил из «просрочено» в «сегодня» — пообещал сделать.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarDays, CalendarRange, Inbox, Sun } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import * as tasksService from '@/services/tasksService'
import type { ListedTask } from '@/services/tasksService'
import { PRIORITY_TONE, dt } from '@/components/tasks/taskWords'

type BucketKey = 'overdue' | 'today' | 'week' | 'later' | 'none'

const BUCKETS: { key: BucketKey; label: string; icon: typeof Sun; hint: string }[] = [
  { key: 'overdue', label: 'Просрочено', icon: AlertTriangle, hint: 'срок уже прошёл' },
  { key: 'today', label: 'Сегодня', icon: Sun, hint: 'сделать сегодня' },
  { key: 'week', label: 'На неделе', icon: CalendarDays, hint: 'ближайшие семь дней' },
  { key: 'later', label: 'Позже', icon: CalendarRange, hint: 'дальше недели' },
  { key: 'none', label: 'Без срока', icon: Inbox, hint: 'когда-нибудь — или в план' },
]

/** В какую колонку попадает задача по её сроку. */
function bucketOf(t: ListedTask): BucketKey {
  if (!t.due_at) return 'none'
  const due = new Date(t.due_at)
  const now = new Date()
  const endToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59)
  if (due < now) return 'overdue'
  if (due <= endToday) return 'today'
  const week = new Date(endToday)
  week.setDate(week.getDate() + 7)
  return due <= week ? 'week' : 'later'
}

/** Новый срок при переносе. «Просрочено» и «без срока» переносом не ставятся:
 *  просрочку нельзя назначить, а снятие срока — отдельное решение в карточке. */
function dueForBucket(key: BucketKey): string | null | undefined {
  const now = new Date()
  if (key === 'today') {
    return new Date(now.getFullYear(), now.getMonth(), now.getDate(), 18, 0).toISOString()
  }
  if (key === 'week') {
    const d = new Date(now); d.setDate(d.getDate() + 7); d.setHours(18, 0, 0, 0)
    return d.toISOString()
  }
  if (key === 'later') {
    const d = new Date(now); d.setDate(d.getDate() + 30); d.setHours(18, 0, 0, 0)
    return d.toISOString()
  }
  return undefined
}

export function TasksDueBoard({ tasks, companyId, onOpen, onChanged }: {
  tasks: ListedTask[]
  companyId: string
  onOpen: (id: string) => void
  onChanged: () => void
}) {
  const qc = useQueryClient()
  const [dragged, setDragged] = useState<string | null>(null)
  const [over, setOver] = useState<BucketKey | null>(null)

  const move = useMutation({
    mutationFn: (v: { id: string; dueAt: string }) =>
      tasksService.taskAction(v.id, { companyId, dueAt: v.dueAt }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const drop = (key: BucketKey) => {
    setOver(null)
    const id = dragged
    setDragged(null)
    const due = dueForBucket(key)
    if (!id || !due) return
    move.mutate({ id, dueAt: due })
  }

  return (
    <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-3">
      {BUCKETS.map((b) => {
        const column = tasks.filter((t) => bucketOf(t) === b.key)
        const droppable = dueForBucket(b.key) !== undefined
        const Icon = b.icon
        return (
          <div key={b.key}
            onDragOver={(e) => { if (droppable) { e.preventDefault(); setOver(b.key) } }}
            onDragLeave={() => setOver((c) => (c === b.key ? null : c))}
            onDrop={() => drop(b.key)}
            className={cn('flex w-[280px] shrink-0 flex-col rounded-xl border bg-muted/30 transition-colors',
              over === b.key && dragged && droppable
                && 'border-primary bg-primary/5 ring-1 ring-primary/30',
              b.key === 'overdue' && 'border-red-500/30')}>
            <div className="flex items-center gap-2 px-3 py-2.5">
              <Icon className={cn('h-3.5 w-3.5',
                b.key === 'overdue' ? 'text-red-500' : 'text-muted-foreground')} />
              <span className="text-[13px] font-medium">{b.label}</span>
              <span className={cn('ml-auto rounded-full px-1.5 py-0.5 text-[11px] tabular-nums',
                column.length ? 'bg-background text-muted-foreground' : 'text-muted-foreground/50')}>
                {column.length}
              </span>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
              {column.map((t) => (
                <div key={t.id} draggable onDragStart={() => setDragged(t.id)}
                  onDragEnd={() => { setDragged(null); setOver(null) }}
                  onClick={() => onOpen(t.id)}
                  className={cn('group cursor-grab rounded-lg border bg-card px-2.5 py-2 text-xs shadow-sm transition-all active:cursor-grabbing',
                    'hover:-translate-y-px hover:border-primary/40 hover:shadow-md',
                    dragged === t.id && 'opacity-40 shadow-none',
                    t.overdue && 'border-red-500/40 bg-red-500/5')}>
                  <div className="flex items-start gap-1.5">
                    {(t.priority === 'high' || t.priority === 'critical') && (
                      <span aria-hidden className={cn('mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                        t.priority === 'critical' ? 'bg-red-500' : 'bg-amber-500')} />
                    )}
                    <span className="flex-1 font-medium leading-snug">{t.title}</span>
                    <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/70">
                      №{t.number}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                    {t.stage && <span>{t.stage}</span>}
                    {t.due_at && (
                      <span className={cn(t.overdue && PRIORITY_TONE.critical)}>{dt(t.due_at)}</span>
                    )}
                    {t.checklist.total > 0 && (
                      <span>{t.checklist.done}/{t.checklist.total}</span>
                    )}
                  </div>
                </div>
              ))}
              {column.length === 0 && (
                <div className={cn('rounded-lg border border-dashed py-8 text-center text-[11px] text-muted-foreground/70 transition-colors',
                  over === b.key && dragged && droppable && 'border-primary/60 text-primary')}>
                  {dragged && droppable ? 'бросьте сюда' : b.hint}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default TasksDueBoard
