/**
 * Календарь в правой рельсе — пульт раскидывания работы, а не второй календарь.
 *
 * Полный месяц с встречами, участниками и согласиями живёт окном из шапки: это
 * работа В календаре. Здесь другое — человек смотрит список дел на большом
 * экране и раскидывает их мышью, не уходя с него:
 *
 * - бросил на число — у задачи стал этот СРОК;
 * - бросил на человека — задача переназначена ему.
 *
 * Отсюда и раскладка: тридцать дней вперёд лентой (месячная сетка в колонке
 * 400 px даёт ячейки, в которые не попасть мышью), под ней — плашки тех, кому
 * этот человек чаще всего поручает.
 *
 * Срок — обязательство перед компанией, поэтому бросок проверяется правами и
 * пишется в след задачи, как любая другая смена срока. Личная дата работы
 * («взял на сегодня») остаётся отдельным действием в строке: это разные вещи,
 * и путать их нельзя.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addDays, format, isSameDay, isToday, isWeekend, startOfDay } from 'date-fns'
import { ru } from 'date-fns/locale'
import { CalendarDays, Loader2, MapPin, UserPlus, Video } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { PlacedList } from '@/components/docs/PlacedList'
import * as workService from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'

/** Сколько дней вперёд показываем. Тридцать — горизонт, на который реально
 *  переносят: дальше срок ставят в карточке, обдумав. */
const ДНЕЙ = 30

/** Предмет из перетаскивания. Чужое (файл, текст, ссылка) молча игнорируем. */
function предмет(e: React.DragEvent): { kind: string; id: string } | null {
  const ref = e.dataTransfer.getData('text/plain')
  const m = /^(task|doc):([0-9a-f-]{36})$/.exec(ref)
  return m ? { kind: m[1], id: m[2] } : null
}

export function CalendarDock() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const companyId = company?.id ?? ''
  const [день, setДень] = useState(() => startOfDay(new Date()))
  const [наведён, setНаведён] = useState<string | null>(null)

  const дни = useMemo(() => Array.from({ length: ДНЕЙ },
    (_, i) => addDays(startOfDay(new Date()), i)), [])

  const события = useQuery({
    queryKey: ['calendar', companyId, 'dock'],
    queryFn: () => workService.listEvents(companyId,
      дни[0].toISOString(), addDays(дни[0], ДНЕЙ).toISOString()),
    enabled: !!companyId,
  })
  const частые = useQuery({
    queryKey: ['frequent-assignees', companyId],
    queryFn: () => workService.frequentAssignees(companyId),
    enabled: !!companyId, staleTime: 10 * 60 * 1000,
  })

  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['work-mine'] })
    void qc.invalidateQueries({ queryKey: ['work'] })
    void qc.invalidateQueries({ queryKey: ['tasks'] })
    void qc.invalidateQueries({ queryKey: ['placed'] })
  }

  const срок = useMutation({
    mutationFn: ({ id, on }: { id: string; on: Date }) => {
      // Конец рабочего дня, а не полночь: «до 3 сентября» человек понимает как
      // «в течение третьего», и полночь делает срок вчерашним.
      const d = new Date(on)
      d.setHours(18, 0, 0, 0)
      return tasksService.taskAction(id, { companyId, dueAt: d.toISOString() })
    },
    onSuccess: (_r, v) => {
      обновить()
      toast.success(`Срок — ${format(v.on, 'd MMMM', { locale: ru })}`)
    },
    onError: (e: Error) => toast.error(e.message || 'Срок не перенёсся'),
  })

  const исполнитель = useMutation({
    mutationFn: ({ id, userId }: { id: string; userId: string }) =>
      tasksService.taskAction(id, { companyId, assigneeId: userId }),
    onSuccess: (_r, v) => {
      обновить()
      const кто = частые.data?.people.find((p) => p.id === v.userId)?.name ?? 'коллеге'
      toast.success(`Поручено: ${кто}`)
    },
    onError: (e: Error) => toast.error(e.message || 'Не переназначилось'),
  })

  if (!companyId) return null

  const встречиДня = (d: Date) => (события.data?.events ?? [])
    .filter((e) => isSameDay(new Date(e.starts_at), d) && e.status !== 'cancelled')

  /** Общий разбор броска: документам срок в доке не двигаем — у него своя
   *  регистрация и своё согласование, и менять его мимо карточки нельзя. */
  const бросок = (e: React.DragEvent, действие: (id: string) => void) => {
    e.preventDefault()
    setНаведён(null)
    const p = предмет(e)
    if (!p) return
    if (p.kind !== 'task') {
      toast.info('Срок документа меняется в его карточке — там же, где регистрация')
      return
    }
    действие(p.id)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b border-border/50 px-3 py-2">
        <CalendarDays className="h-4 w-4 shrink-0 text-primary" />
        <span className="flex-1 text-sm font-medium">Ближайшие 30 дней</span>
      </header>

      <p className="shrink-0 px-3 pt-2 text-xs text-muted-foreground">
        Перетащите задачу на день — у неё станет этот срок. На человека внизу —
        поручите ему.
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        <ul className="space-y-0.5">
          {дни.map((d) => {
            const ключ = workService.todayKey(d)
            const встречи = встречиДня(d).length
            const выбран = isSameDay(d, день)
            return (
              <li key={ключ}>
                <button type="button" onClick={() => setДень(d)}
                  onDragOver={(e) => { e.preventDefault(); setНаведён(ключ) }}
                  onDragLeave={() => setНаведён((k) => (k === ключ ? null : k))}
                  onDrop={(e) => бросок(e, (id) => срок.mutate({ id, on: d }))}
                  className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                    наведён === ключ && 'ring-2 ring-primary',
                    выбран ? 'bg-primary/10 text-primary'
                      : isWeekend(d) ? 'text-muted-foreground/70 hover:bg-accent/40'
                        : 'text-foreground hover:bg-accent/40')}>
                  <span className="w-8 shrink-0 text-right tabular-nums">{format(d, 'd')}</span>
                  <span className="w-8 shrink-0 text-xs text-muted-foreground">
                    {format(d, 'EEEEEE', { locale: ru })}
                  </span>
                  <span className="flex-1 truncate text-xs text-muted-foreground">
                    {isToday(d) ? 'сегодня'
                      : format(d, 'LLLL', { locale: ru })}
                  </span>
                  {встречи > 0 && (
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {встречи} встр.
                    </span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      {/* Плашки тех, кому этот человек чаще всего поручает: бросок сюда
          переназначает исполнителя. Список считается по его же постановкам —
          у каждого он свой. */}
      {(частые.data?.people.length ?? 0) > 0 && (
        <div className="shrink-0 border-t border-border/50 px-3 py-2">
          <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <UserPlus className="h-3.5 w-3.5" />Поручить
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {(частые.data?.people ?? []).map((p) => (
              <button key={p.id} type="button"
                onDragOver={(e) => { e.preventDefault(); setНаведён(p.id) }}
                onDragLeave={() => setНаведён((k) => (k === p.id ? null : k))}
                onDrop={(e) => бросок(e, (id) => исполнитель.mutate({ id, userId: p.id }))}
                onClick={() => toast.info('Перетащите сюда задачу — она уйдёт этому человеку')}
                title={`${p.name}: ${p.count} поручений за три месяца`}
                className={cn('max-w-[150px] truncate rounded-md border border-border px-2 py-1 text-xs transition-colors',
                  наведён === p.id
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
                {p.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="max-h-[45%] shrink-0 space-y-3 overflow-y-auto border-t border-border/50 px-3 py-2">
        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Встречи · {format(день, 'd MMMM', { locale: ru })}
          </h3>
          {события.isLoading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />Смотрим календарь…
            </p>
          ) : встречиДня(день).length === 0 ? (
            <p className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground">
              Встреч нет.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border">
              {встречиДня(день).map((e) => (
                <div key={e.id} className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0">
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {format(new Date(e.starts_at), 'HH:mm')}
                  </span>
                  <span className="flex-1 truncate text-sm">{e.title}</span>
                  {e.conference_url && <Video className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                  {e.location && <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Взято на день
          </h3>
          <PlacedList companyId={companyId} scope="day" on={workService.todayKey(день)}
            empty="Ничего не взято на этот день." />
        </section>
      </div>
    </div>
  )
}

export default CalendarDock
