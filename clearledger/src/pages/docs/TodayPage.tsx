/**
 * «Сегодня» — день целиком: что просрочено, что на сегодня, о чём просил
 * напомнить.
 *
 * Отличается от «Моей очереди» одним вопросом. Очередь отвечает «что на мне
 * вообще» и потому длинная; сюда человек заходит утром спросить «что сегодня»
 * — и список на два экрана этот вопрос не закрывает, а прячет.
 *
 * Список сроков не пишется заново: это та же `MyWorkPage` с двумя корзинами.
 * Второй экземпляр строки очереди разошёлся бы с первым на первой же правке —
 * действие в строке, пустое состояние, цвет просрочки.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Check, Clock3, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { PersonalReminder } from '@/services/workService'
import { MyWorkPage } from './MyWorkPage'
import { dtT } from '@/components/tasks/taskWords'

/** Как сегодня называется вслух: «понедельник, 25 августа». */
const сегодня = () => new Date().toLocaleDateString('ru-RU', {
  weekday: 'long', day: 'numeric', month: 'long',
})

export function TodayPage() {
  const { company } = useCompany()
  const companyId = company?.id ?? ''

  if (!companyId) return null

  return (
    <div className="space-y-5 p-4">
      <header>
        <h1 className="text-lg font-semibold text-foreground">Сегодня</h1>
        <p className="mt-0.5 text-xs text-muted-foreground first-letter:uppercase">{сегодня()}</p>
      </header>

      <Reminders companyId={companyId} />

      <section>
        <h2 className="mb-1.5 text-sm font-medium text-foreground">Сроки</h2>
        <MyWorkPage buckets={['overdue', 'today']} heading={false} />
      </section>
    </div>
  )
}

/** Сработавшие напоминания: их гасят или откладывают прямо здесь. */
function Reminders({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['reminders', companyId, 'pending'],
    queryFn: () => workService.listReminders(companyId, { pending: true }),
    refetchInterval: 60_000,
  })
  const act = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof workService.reminderAction>[2] }) =>
      workService.reminderAction(companyId, id, data),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['reminders', companyId] }) },
    onError: (e: Error) => toast.error(e.message || 'Не получилось'),
  })

  const rows = q.data?.items ?? []
  if (q.isLoading) {
    return (
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />Смотрю напоминания…
      </p>
    )
  }
  if (rows.length === 0) return null

  return (
    <section>
      <h2 className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-foreground">
        <Bell className="h-3.5 w-3.5 text-primary" />Напоминания
        <span className="text-xs font-normal text-muted-foreground">{rows.length}</span>
      </h2>
      <div className="overflow-hidden rounded-lg border border-border">
        {rows.map((r) => (
          <Row key={r.id} row={r} busy={act.isPending}
            onSnooze={(minutes) => act.mutate({ id: r.id, data: { snoozeMinutes: minutes } })}
            onDone={() => act.mutate({ id: r.id, data: { done: true } })} />
        ))}
      </div>
    </section>
  )
}

function Row({ row, busy, onSnooze, onDone }: {
  row: PersonalReminder; busy: boolean
  onSnooze: (minutes: number) => void; onDone: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border px-3 py-2 last:border-0">
      <span className="min-w-[12rem] flex-1 text-sm text-foreground">
        {row.note || 'Напоминание'}
      </span>
      <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
        <Clock3 className="h-3 w-3" />{dtT(row.remind_at)}
      </span>
      {/* Сколько раз откладывали — единственный сигнал, который личный помощник
          может вернуть человеку: отложенное шестой раз это дело, которого не
          будет, и полезнее решить его судьбу, чем двигать дальше. */}
      {row.snooze_count > 2 && (
        <span className="text-[11px] text-amber-600 dark:text-amber-400">
          откладывали {row.snooze_count} {раз(row.snooze_count)}
        </span>
      )}
      <span className="flex items-center gap-1">
        <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" disabled={busy}
          onClick={() => onSnooze(60)}>Через час</Button>
        <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" disabled={busy}
          onClick={() => onSnooze(60 * 24)}>Завтра</Button>
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={busy}
          title="Больше не напоминать" onClick={onDone}>
          <Check className="h-3.5 w-3.5" />
        </Button>
      </span>
    </div>
  )
}

/** «3 раза», «5 раз» — счётчик, читающийся как ошибка, доверия не прибавляет. */
const раз = (n: number) => {
  const две = n % 100
  if (две > 4 && две < 21) return 'раз'
  const одна = n % 10
  return одна > 1 && одна < 5 ? 'раза' : 'раз'
}

export default TodayPage
