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
import {
  addDays, eachDayOfInterval, format, isBefore, isSameDay, isSameMonth, isToday,
  isWeekend, startOfDay, startOfWeek,
} from 'date-fns'
import { ru } from 'date-fns/locale'
import { CalendarDays, Loader2, MapPin, UserCheck, UserPlus, Video } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { PlacedList } from '@/components/docs/PlacedList'
import * as workService from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import { cn } from '@/lib/utils'

/** Пять недель от понедельника текущей: горизонт, на который реально переносят,
 *  а дальше срок ставят в карточке, обдумав. Недели остаются неделями. */
const НЕДЕЛИ = 5
const ДНИ_НЕДЕЛИ = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

/** Предмет из перетаскивания. Чужое (файл, текст, ссылка) молча игнорируем. */
function предмет(e: React.DragEvent): { kind: string; id: string } | null {
  const ref = e.dataTransfer.getData('text/plain')
  const m = /^(task|doc):([0-9a-f-]{36})$/.exec(ref)
  return m ? { kind: m[1], id: m[2] } : null
}

export function CalendarDock() {
  const { company } = useCompany()
  const { user } = useAuth()
  const я = user?.id ?? ''
  const qc = useQueryClient()
  const companyId = company?.id ?? ''
  const [день, setДень] = useState(() => startOfDay(new Date()))
  const [наведён, setНаведён] = useState<string | null>(null)

  // Сетка начинается с понедельника ТЕКУЩЕЙ недели: календарь, у которого первая
  // строка начинается со среды, перестаёт читаться как календарь.
  const начало = useMemo(() => startOfWeek(startOfDay(new Date()), { weekStartsOn: 1 }), [])
  const дни = useMemo(() => eachDayOfInterval({
    start: начало, end: addDays(начало, НЕДЕЛИ * 7 - 1),
  }), [начало])
  const сегодня = useMemo(() => startOfDay(new Date()), [])

  const события = useQuery({
    // Границы окна — часть ключа: вкладка, оставленная открытой через полночь,
    // иначе продолжает показывать вчерашнюю сетку.
    queryKey: ['calendar', companyId, 'dock', workService.todayKey(дни[0])],
    queryFn: () => workService.listEvents(companyId,
      дни[0].toISOString(), addDays(дни[0], НЕДЕЛИ * 7).toISOString()),
    enabled: !!companyId,
  })
  const частые = useQuery({
    queryKey: ['frequent-assignees', companyId],
    queryFn: () => workService.frequentAssignees(companyId),
    enabled: !!companyId, staleTime: 10 * 60 * 1000,
  })
  const люди = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })

  /** Кому поручают: все в пространстве, частые адресаты первыми. Порядок и есть
   *  подсказка — отдельного блока «избранные» не заводим. */
  const адресаты = useMemo(() => {
    const вес = new Map((частые.data?.people ?? []).map((p) => [p.id, p.count]))
    // Себя в общем списке нет: он стоит отдельной строкой над всеми. Иначе
    // «забрать себе» приходилось искать среди двух десятков фамилий, хотя это
    // самое частое, что делают с чужой работой.
    return [...(люди.data?.people ?? [])].filter((p) => p.id !== я)
      .sort((a, b) => (вес.get(b.id) ?? 0) - (вес.get(a.id) ?? 0)
        || a.name.localeCompare(b.name, 'ru'))
  }, [люди.data, частые.data, я])

  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['work-mine'] })
    void qc.invalidateQueries({ queryKey: ['work'] })
    void qc.invalidateQueries({ queryKey: ['tasks'] })
    void qc.invalidateQueries({ queryKey: ['placed'] })
  }

  /** Записать себе на выбранный день. Пульт раскидывания умел двигать чужое, а
   *  «поставить себе напоминание» отправлял человека искать другое окно —
   *  притом что день уже выбран мышью в этой же сетке. */
  const [черновик, setЧерновик] = useState('')
  const записать = useMutation({
    mutationFn: () => {
      const d = new Date(день)
      d.setHours(18, 0, 0, 0)
      return tasksService.createTask({
        companyId, title: черновик.trim(),
        // Исполнитель ЯВНЫЙ: задача без исполнителя ничья и в «Моей очереди»
        // (отбор идёт по исполнителю) не появляется вовсе.
        assigneeId: я || undefined,
        dueAt: d.toISOString(),
      })
    },
    onSuccess: (t) => {
      setЧерновик('')
      обновить()
      toast.success(`${tasksService.taskKey(t)} — себе на ${format(день, 'd MMMM', { locale: ru })}`)
    },
    onError: (e: Error) => toast.error(e.message || 'Не записалось'),
  })

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
      const кто = адресаты.find((p) => p.id === v.userId)?.name ?? 'коллеге'
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
        {/* Пять недель от понедельника текущей: вперёд остаётся от 28 до 34 дней,
            и обещать ровно тридцать — неправда. */}
        <span className="flex-1 text-sm font-medium">Пять недель</span>
      </header>

      <p className="shrink-0 px-3 pt-2 text-xs text-muted-foreground">
        Тащите строку работы из «Трека» — из «Моей очереди», «Поручений» или с
        доски (слева от названия есть ручка). На день — у неё станет этот срок,
        на «Мне» внизу — заберёте себе, на человека — поручите ему.
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        <div className="grid grid-cols-7 gap-1 pb-1 text-center text-xs text-muted-foreground">
          {ДНИ_НЕДЕЛИ.map((d) => <div key={d}>{d}</div>)}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {дни.map((d) => {
            const ключ = workService.todayKey(d)
            const встречи = встречиДня(d).length
            const выбран = isSameDay(d, день)
            const прошёл = isBefore(d, сегодня)
            const первыйВМесяце = d.getDate() === 1
            return (
              <button key={ключ} type="button" onClick={() => setДень(d)}
                disabled={прошёл}
                onDragOver={(e) => { if (!прошёл) { e.preventDefault(); setНаведён(ключ) } }}
                onDragLeave={() => setНаведён((k) => (k === ключ ? null : k))}
                onDrop={(e) => бросок(e, (id) => срок.mutate({ id, on: d }))}
                title={`${format(d, 'd MMMM, EEEE', { locale: ru })}`
                  + (встречи ? ` · встреч: ${встречи}` : '')
                  + (прошёл ? ' · день прошёл' : '')}
                className={cn('relative flex aspect-square flex-col items-center justify-center rounded-md text-sm transition-colors',
                  наведён === ключ && 'ring-2 ring-primary',
                  прошёл ? 'text-muted-foreground/35'
                    : выбран ? 'bg-primary text-primary-foreground'
                      : isToday(d) ? 'bg-primary/15 font-semibold text-primary'
                        : isWeekend(d) ? 'text-muted-foreground hover:bg-accent'
                          : 'text-foreground hover:bg-accent')}>
                <span className="tabular-nums leading-none">{format(d, 'd')}</span>
                {/* Первое число подписывает месяц: без этого пятая неделя висит
                    без ответа на вопрос «а это какой месяц». */}
                {первыйВМесяце && !прошёл && (
                  <span className="mt-0.5 text-xs uppercase leading-none opacity-70">
                    {format(d, 'LLL', { locale: ru })}
                  </span>
                )}
                {встречи > 0 && !первыйВМесяце && (
                  <span className={cn('mt-1 h-1 w-1 rounded-full',
                    выбран ? 'bg-primary-foreground' : 'bg-primary')} aria-hidden />
                )}
              </button>
            )
          })}
        </div>
        {!isSameMonth(дни[0], дни[дни.length - 1]) && (
          <p className="pt-2 text-center text-xs text-muted-foreground">
            {format(дни[0], 'LLLL', { locale: ru })} — {format(дни[дни.length - 1], 'LLLL yyyy', { locale: ru })}
          </p>
        )}
      </div>

      {/* Записать себе: день уже выбран в сетке выше, поэтому строка ставит
          работу сразу со сроком. Тип, проект и подробности — потом в карточке. */}
      <div className="shrink-0 border-t border-border/50 px-3 py-2">
        <input value={черновик} onChange={(e) => setЧерновик(e.target.value)}
          maxLength={300}
          placeholder={`Записать себе на ${format(день, 'd MMMM', { locale: ru })} — Enter`}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && черновик.trim().length >= 3 && !записать.isPending) {
              записать.mutate()
            }
          }}
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      </div>

      {/* Кому поручить: весь список пространства, две колонки. Бросок на строку
          переназначает исполнителя. */}
      {(адресаты.length > 0 || !!я) && (
        <div className="shrink-0 border-t border-border/50 px-3 py-2">
          <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <UserPlus className="h-3.5 w-3.5" />Поручить
          </h3>
          {/* «Мне» — отдельной строкой во всю ширину и с акцентом: забрать
              работу себе просят чаще, чем поручить конкретному человеку, а
              среди двух десятков фамилий своя ничем не выделялась. */}
          {!!я && (
            <button type="button"
              onDragOver={(e) => { e.preventDefault(); setНаведён(я) }}
              onDragLeave={() => setНаведён((k) => (k === я ? null : k))}
              onDrop={(e) => бросок(e, (id) => исполнитель.mutate({ id, userId: я }))}
              onClick={() => toast.info('Перетащите сюда задачу — заберёте её себе')}
              title="Перетащите сюда задачу — она станет вашей"
              className={cn('mb-1 flex w-full items-center gap-1.5 rounded-md border border-dashed px-2 py-1.5 text-left text-xs font-medium transition-colors',
                наведён === я
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-primary/40 bg-primary/5 text-primary hover:bg-primary/10')}>
              <UserCheck className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">Мне{user?.name ? ` · ${user.name}` : ''}</span>
            </button>
          )}
          <div className="grid max-h-32 grid-cols-2 gap-1 overflow-y-auto">
            {адресаты.map((p) => (
              <button key={p.id} type="button"
                onDragOver={(e) => { e.preventDefault(); setНаведён(p.id) }}
                onDragLeave={() => setНаведён((k) => (k === p.id ? null : k))}
                onDrop={(e) => бросок(e, (id) => исполнитель.mutate({ id, userId: p.id }))}
                onClick={() => toast.info('Перетащите сюда задачу — она уйдёт этому человеку')}
                title={`${p.name} — перетащите сюда задачу`}
                className={cn('truncate rounded-md border border-border px-2 py-1 text-left text-xs transition-colors',
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
