/**
 * «Сегодня» — день целиком: что я взял, что принесла компания, о чём просил
 * напомнить.
 *
 * Отличается от «Моей очереди» одним вопросом. Очередь отвечает «что на мне
 * вообще» и потому длинная; сюда человек заходит утром спросить «что сегодня»
 * — и список на два экрана этот вопрос не закрывает, а прячет.
 *
 * Две полосы, а не одна, потому что у работы разное происхождение. Компания
 * приносит визы, поручения и сроки — отменить их человек не вправе. Свой день
 * он набирает сам: взять, отложить до даты, отдать. Прежний экран показывал
 * только принесённое, и места для решения человека в продукте не было.
 *
 * Список сроков не пишется заново: это та же `MyWorkPage` с двумя корзинами.
 * Второй экземпляр строки очереди разошёлся бы с первым на первой же правке —
 * действие в строке, пустое состояние, цвет просрочки.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Bell, Check, ChevronDown, ChevronRight, Clock3, EyeOff, Loader2, Sun,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import type { PersonalReminder } from '@/services/workService'
import { PlacedList } from '@/components/docs/PlacedList'
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
      <CarryOver companyId={companyId} />

      <section>
        <h2 className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-foreground">
          <Sun className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />Мой день
        </h2>
        <PlacedList companyId={companyId} scope="day"
          empty="День пуст. Возьмите из того, что ниже, — или оставьте пустым: это тоже решение." />
      </section>

      <section>
        <h2 className="mb-1.5 text-sm font-medium text-foreground">Ждут от вас</h2>
        <p className="mb-1.5 text-xs text-muted-foreground">
          Принесла компания. Взять в день, отложить у себя или отдать — ваше
          решение; срок и состояние предмета при этом не меняются.
        </p>
        <MyWorkPage buckets={['overdue', 'today']} heading={false} hideDeferred hideTaken />
      </section>

      <Deferred companyId={companyId} />
    </div>
  )
}


/** Вчера взятое и не закрытое. Само в новый день не переезжает: сброс работает
 *  только рядом с утренним вопросом «переносим?» — иначе человек молча теряет
 *  невзятое, а день перестаёт быть его решением. */
function CarryOver({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const q = useQuery({
    queryKey: ['placed', companyId, 'carry', ''],
    queryFn: () => workService.placed(companyId, { scope: 'carry' }),
  })
  const rows = q.data?.items ?? []

  const move = useMutation({
    mutationFn: async () => {
      for (const item of rows) {
        await workService.place(companyId, workService.targetRef(item),
                                { takenFor: workService.todayKey() })
      }
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['placed', companyId] })
      toast.success('Перенесено в сегодня')
    },
    onError: (e: Error) => toast.error(e.message || 'Не перенеслось'),
  })

  if (rows.length === 0) return null

  return (
    <section className="rounded-lg border border-amber-500/40 bg-amber-500/[0.04] px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="flex-1 text-sm text-foreground">
          Вчера осталось {rows.length} {дел(rows.length)}
        </span>
        <Button size="sm" className="h-8 px-2 text-xs" disabled={move.isPending}
          onClick={() => move.mutate()}>
          {move.isPending && <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />}
          Перенести в сегодня
        </Button>
        <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
          onClick={() => setOpen((v) => !v)}>
          {open ? 'Свернуть' : 'Посмотреть'}
        </Button>
      </div>
      {open && (
        <div className="mt-2">
          <PlacedList companyId={companyId} scope="carry" empty="Пусто" />
        </div>
      )}
    </section>
  )
}


/** Отложенное человеком. Свёрнуто, но со счётчиком и всегда на виду: скрытое
 *  без обзора не убрано, а забыто. */
function Deferred({ companyId }: { companyId: string }) {
  const [open, setOpen] = useState(false)
  const q = useQuery({
    queryKey: ['placed', companyId, 'deferred', ''],
    queryFn: () => workService.placed(companyId, { scope: 'deferred' }),
  })
  const count = q.data?.items.length ?? 0
  if (count === 0) return null

  return (
    <section>
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <EyeOff className="h-3.5 w-3.5" />Отложено
        <span className="text-xs font-normal tabular-nums">{count}</span>
      </button>
      {open && (
        <div className="mt-1.5">
          <p className="mb-1.5 text-xs text-muted-foreground">
            Спрятано только у вас. Срок компании шёл всё это время и не менялся.
          </p>
          <PlacedList companyId={companyId} scope="deferred" empty="Ничего не отложено" />
        </div>
      )}
    </section>
  )
}


/** «1 дело», «2 дела», «5 дел» — счётчик с ошибкой согласования читается как
 *  небрежность продукта. */
const дел = (n: number) => {
  const две = n % 100
  if (две > 4 && две < 21) return 'дел'
  const одна = n % 10
  if (одна === 1) return 'дело'
  return одна > 1 && одна < 5 ? 'дела' : 'дел'
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
  const navigate = useNavigate()
  // Откладывали трижды — предлагаем другое, а не то же самое. На измеренных
  // данных отклонивший первое напоминание серии отклоняет следующие в 88%
  // случаев, и дело не в привыкании, а в перегрузке: повторять ту же кнопку
  // бессмысленно. Решение живёт в карточке предмета — там и срок, и исполнитель,
  // и чек-лист, на который работу разбивают.
  const застряло = row.snooze_count > 2
  const куда = workService.refHref(row.target_ref)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border px-3 py-2 last:border-0">
      <span className="min-w-[12rem] flex-1 text-sm text-foreground">
        {row.note || 'Напоминание'}
      </span>
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Clock3 className="h-3 w-3" />{dtT(row.remind_at)}
      </span>
      {застряло && (
        <span className="text-xs text-amber-600 dark:text-amber-400">
          откладывали {row.snooze_count} {раз(row.snooze_count)} — перенесите срок,
          передайте или снимите
        </span>
      )}
      <span className="flex items-center gap-1">
        {застряло ? (
          куда && (
            <Button size="sm" variant="outline" className="h-8 px-2 text-xs"
              disabled={busy} onClick={() => navigate(куда)}>Заняться</Button>
          )
        ) : (
          <>
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs" disabled={busy}
              onClick={() => onSnooze(60)}>Через час</Button>
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs" disabled={busy}
              onClick={() => onSnooze(60 * 24)}>Завтра</Button>
          </>
        )}
        <Button size="sm" variant="ghost" className="h-8 px-2" disabled={busy}
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
