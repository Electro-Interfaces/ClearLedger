/**
 * Календарь в правой рельсе — не второй календарь, а способ положить работу на
 * день, не уходя с экрана.
 *
 * Полный календарь живёт окном: месяц с встречами, участниками и согласиями —
 * это работа В календаре. Здесь другое: человек смотрит очередь или реестр,
 * видит дело и бросает его на четверг. Поэтому сетка мелкая, а главное в ней —
 * не показать месяц, а принять предмет.
 *
 * Что означает бросок. Дату РАБОТЫ («когда я этим займусь»), а не срок. Срок —
 * обязательство перед компанией, его переносят в карточке и с причиной; личный
 * план двигается сколько угодно и никого не касается. Это то же разделение,
 * к которому пришли Things, OmniFocus и Todoist, и ровно поэтому бросок сюда
 * безопасен: он не может испортить чужое обещание.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addMonths, eachDayOfInterval, endOfMonth, endOfWeek, format, isSameDay,
  isSameMonth, isToday, startOfMonth, startOfWeek,
} from 'date-fns'
import { ru } from 'date-fns/locale'
import { CalendarDays, ChevronLeft, ChevronRight, Loader2, MapPin, Video } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { PlacedList } from '@/components/docs/PlacedList'
import * as workService from '@/services/workService'
import { cn } from '@/lib/utils'

const ДНИ = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

export function CalendarDock() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const companyId = company?.id ?? ''
  const [месяц, setМесяц] = useState(() => startOfMonth(new Date()))
  const [день, setДень] = useState(() => new Date())
  const [наведён, setНаведён] = useState<string | null>(null)

  const сетка = useMemo(() => eachDayOfInterval({
    start: startOfWeek(startOfMonth(месяц), { weekStartsOn: 1 }),
    end: endOfWeek(endOfMonth(месяц), { weekStartsOn: 1 }),
  }), [месяц])

  const события = useQuery({
    queryKey: ['calendar', companyId, format(месяц, 'yyyy-MM')],
    queryFn: () => workService.listEvents(companyId,
      startOfWeek(startOfMonth(месяц), { weekStartsOn: 1 }).toISOString(),
      endOfWeek(endOfMonth(месяц), { weekStartsOn: 1 }).toISOString()),
    enabled: !!companyId,
  })

  const принять = useMutation({
    mutationFn: ({ ref, on }: { ref: string; on: Date }) =>
      workService.place(companyId, ref, { takenFor: workService.todayKey(on) }),
    onSuccess: (_r, v) => {
      void qc.invalidateQueries({ queryKey: ['placed'] })
      void qc.invalidateQueries({ queryKey: ['work-mine'] })
      toast.success(`Взято на ${format(v.on, 'd MMMM', { locale: ru })}`,
                    { description: 'Срок предмета не изменился' })
    },
    onError: (e: Error) => toast.error(e.message || 'Не легло на день'),
  })

  if (!companyId) return null

  const встречиДня = (d: Date) => (события.data?.events ?? [])
    .filter((e) => isSameDay(new Date(e.starts_at), d) && e.status !== 'cancelled')

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-1 border-b border-border/50 px-3 py-2">
        <CalendarDays className="h-4 w-4 shrink-0 text-primary" />
        <span className="flex-1 truncate text-sm font-medium first-letter:uppercase">
          {format(месяц, 'LLLL yyyy', { locale: ru })}
        </span>
        <Button size="sm" variant="ghost" className="h-8 w-8 p-0"
          aria-label="Прошлый месяц" onClick={() => setМесяц((m) => addMonths(m, -1))}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button size="sm" variant="ghost" className="h-8 w-8 p-0"
          aria-label="Следующий месяц" onClick={() => setМесяц((m) => addMonths(m, 1))}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </header>

      <p className="shrink-0 px-3 pt-2 text-xs text-muted-foreground">
        Перетащите сюда дело — оно встанет на этот день у вас. Срок компании при
        этом не меняется.
      </p>

      <div className="shrink-0 px-2 py-2">
        <div className="grid grid-cols-7 gap-px text-center text-xs text-muted-foreground">
          {ДНИ.map((d) => <div key={d} className="py-1">{d}</div>)}
        </div>
        <div className="grid grid-cols-7 gap-px">
          {сетка.map((d) => {
            const ключ = workService.todayKey(d)
            const встречи = встречиДня(d).length
            const выбран = isSameDay(d, день)
            return (
              <button key={ключ} type="button" onClick={() => setДень(d)}
                onDragOver={(e) => { e.preventDefault(); setНаведён(ключ) }}
                onDragLeave={() => setНаведён((k) => (k === ключ ? null : k))}
                onDrop={(e) => {
                  e.preventDefault()
                  setНаведён(null)
                  const ref = e.dataTransfer.getData('text/plain')
                  // Чужое перетаскивание (файл, текст) роняет не должно: словарь
                  // предмета известен, всё остальное просто игнорируется.
                  if (/^(task|doc):[0-9a-f-]{36}$/.test(ref)) {
                    принять.mutate({ ref, on: d })
                    setДень(d)
                  }
                }}
                className={cn('relative flex h-9 flex-col items-center justify-center rounded-md text-xs transition-colors',
                  наведён === ключ && 'ring-2 ring-primary ring-offset-1 ring-offset-background',
                  выбран ? 'bg-primary text-primary-foreground'
                    : isToday(d) ? 'bg-primary/10 font-medium text-primary'
                      : isSameMonth(d, месяц) ? 'text-foreground hover:bg-accent'
                        : 'text-muted-foreground/50 hover:bg-accent/50')}>
                <span className="tabular-nums leading-none">{format(d, 'd')}</span>
                {встречи > 0 && (
                  <span className={cn('mt-0.5 h-1 w-1 rounded-full',
                    выбран ? 'bg-primary-foreground' : 'bg-primary')} aria-hidden />
                )}
              </button>
            )
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pb-3">
        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Встречи · {format(день, 'd MMMM', { locale: ru })}
          </h3>
          {события.isLoading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />Смотрим календарь…
            </p>
          ) : встречиДня(день).length === 0 ? (
            <p className="rounded-lg border border-border px-3 py-3 text-xs text-muted-foreground">
              Встреч нет.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border">
              {встречиДня(день).map((e) => (
                <div key={e.id} className="border-b px-3 py-2 last:border-b-0">
                  <div className="flex items-center gap-2">
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {format(new Date(e.starts_at), 'HH:mm')}
                    </span>
                    <span className="flex-1 truncate text-sm">{e.title}</span>
                    {e.conference_url && <Video className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                    {e.location && <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Дела на день
          </h3>
          <PlacedList companyId={companyId} scope="day" on={workService.todayKey(день)}
            empty="Ничего не взято на этот день. Перетащите дело на число выше." />
        </section>
      </div>
    </div>
  )
}

export default CalendarDock
