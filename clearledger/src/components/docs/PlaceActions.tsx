/**
 * Действия личной раскладки в строке работы: взять в день, отложить, положить
 * в подборку, пометить важным.
 *
 * Одним компонентом на все экраны намеренно: раскладку трогают из очереди, из
 * «Сегодня» и из самой подборки, и три копии этих кнопок разошлись бы на первой же
 * правке — а правило здесь одно и оно неочевидное.
 *
 * Что этот компонент НЕ делает: не меняет предмет. Срок, состояние и просрочка
 * остаются такими, какими их видит компания; «отложить» прячет строку у себя, а
 * не двигает обязательство. Поэтому сервер вправе отказать — просроченное не
 * прячется, — и отказ показывается человеку словами, а не молчаливым откатом.
 */
import { useState } from 'react'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarCheck, CalendarClock, FolderPlus, MoreHorizontal, Star, Sun, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent,
  DropdownMenuSubTrigger, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import * as workService from '@/services/workService'
import type { PersonalMark } from '@/services/workService'
import { shortDay } from '@/lib/personalDay'
import { cn } from '@/lib/utils'

/** Ближайший день недели вперёд: «в понедельник» — самый частый ответ на
 *  вопрос «когда вернуться», и считать его человеку не должно приходиться. */
function nextWeekday(target: number): string {
  const d = new Date()
  // Остаток по семи обязателен: без него в воскресенье «до понедельника»
  // означало понедельник СЛЕДУЮЩЕЙ недели — плюс восемь дней вместо одного.
  d.setDate(d.getDate() + (((target - d.getDay() + 7) % 7) || 7))
  return workService.todayKey(d)
}

const завтра = () => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return workService.todayKey(d)
}

export function PlaceActions({
  companyId, targetRef, mark, dueAt, onChanged, compact: compactProp,
}: {
  companyId: string
  targetRef: string
  mark: PersonalMark | null | undefined
  /** Срок предмета. По нему считается, можно ли его прятать: сервер
   *  отказывает, когда срок наступил или прошёл, и знать об этом надо ДО
   *  нажатия, а не после. Передаётся сам срок, а не признак просрочки, —
   *  признак отставал на день: у работы со сроком СЕГОДНЯ просрочки ещё нет,
   *  а спрятать её уже нельзя. */
  dueAt?: string | null
  onChanged: () => void
  /** В плотных списках звезда и день прячутся в меню. */
  compact?: boolean
}) {
  const qc = useQueryClient()
  const mobile = useMaxWidth(640)
  const compact = compactProp || mobile
  /** Что именно выбирают днём: запланировать работу или спрятать до даты.
   *  Поле ввода одно, намерения два — и путать их нельзя. */
  const [pickingDate, setPickingDate] = useState<'plan' | 'defer' | null>(null)
  const [date, setDate] = useState('')

  const lists = useQuery({
    queryKey: ['personal-lists', companyId],
    queryFn: () => workService.myLists(companyId),
    staleTime: 5 * 60 * 1000,
  })

  const act = useMutation({
    mutationFn: (data: Parameters<typeof workService.place>[2]) =>
      workService.place(companyId, targetRef, data),
    onSuccess: (res) => {
      setPickingDate(null)
      // Ответ сервера — уже посчитанная отметка: кладём её в очередь и в списки
      // раскладки, не дожидаясь повторной загрузки. Иначе открытое меню
      // продолжает называть подборку, из которой предмет только что убрали.
      const today = workService.todayKey()
      qc.setQueriesData<{ mine: workService.MyWorkItem[] } | undefined>(
        { queryKey: ['work-mine'] },
        (old) => (old ? {
          ...old,
          mine: old.mine.map((r) => (workService.targetRef(r) === res.target_ref
            ? {
              ...r,
              mark: res.mark,
              in_day: res.mark?.taken_for === today,
              hidden: !!res.mark?.deferred_until && res.mark.deferred_until > today,
            }
            : r)),
        } : old))
      qc.setQueriesData<{ items: workService.PlacedItem[] } | undefined>(
        { queryKey: ['placed'] },
        (old) => (old ? {
          ...old,
          items: old.items.map((r) => (workService.targetRef(r) === res.target_ref
            ? { ...r, mark: res.mark } : r)),
        } : old))
      onChanged()
      void qc.invalidateQueries({ queryKey: ['personal-lists', companyId] })
      void qc.invalidateQueries({ queryKey: ['placed'] })
    },
    // Сообщение сервера показываем как есть: оно объясняет правило («срок уже
    // прошёл: просроченное не прячется»), а «не получилось» не объясняет ничего.
    onError: (e: Error) => toast.error(e.message || 'Не получилось'),
  })

  /** Прятать нельзя, когда срок наступил или прошёл. Та же граница, что в
   *  `placement.clamp_defer` на сервере: расхождение на день означало отказ
   *  после нажатия — ровно то, чего эта проверка и должна избегать. */
  const нельзяПрятать = !!dueAt
    && workService.todayKey(new Date(dueAt)) <= workService.todayKey()

  const inDay = mark?.taken_for === workService.todayKey()
  /** День, на который человек запланировал работу, — включая сегодняшний.
   *  Отличается от `inDay` тем, что отвечает на «когда», а не «сейчас ли». */
  const planned = mark?.taken_for ?? null
  const deferred = mark?.deferred_until ?? null
  const listName = lists.data?.lists.find((l) => l.id === mark?.list_id)?.name

  /** Пустая отметка проступает при наведении и с клавиатуры; поставленная
   *  видна всегда. Правый край строки — дорожка, по которой глаз ищет срок, и
   *  два серых значка на каждой строке эту дорожку загораживают.
   *
   *  Там, где наведения не бывает (палец), видно всё: спрятать действие от
   *  того, кто не может навести, значит убрать его. */
  const тихо = (поставлено: boolean | undefined) => (поставлено ? '' : cn(
    'opacity-0 transition-opacity',
    'group-hover/строка:opacity-100 group-focus-within/строка:opacity-100',
    'focus-visible:opacity-100',
    '[@media(hover:none)]:opacity-100',
  ))

  const кнопкаДня = (
    <Button size="sm" variant="ghost" disabled={act.isPending}
      className={cn('h-8 px-2', тихо(inDay),
        inDay && 'text-amber-600 dark:text-amber-400')}
      title={inDay ? 'Убрать из моего дня' : 'Взять в мой день'}
      onClick={() => act.mutate(inDay
        ? { dropDay: true }
        : { takenFor: workService.todayKey() })}>
      <Sun className={cn('h-3.5 w-3.5', inDay && 'fill-current')} />
    </Button>
  )

  const кнопкаЗвезды = (
    <Button size="sm" variant="ghost" disabled={act.isPending}
      className={cn('h-8 px-2', тихо(mark?.starred),
        mark?.starred && 'text-amber-600 dark:text-amber-400')}
      title={mark?.starred ? 'Снять важность' : 'Важно для меня'}
      onClick={() => act.mutate({ starred: !mark?.starred })}>
      <Star className={cn('h-3.5 w-3.5', mark?.starred && 'fill-current')} />
    </Button>
  )

  if (pickingDate) {
    const планирую = pickingDate === 'plan'
    return (
      <span className="inline-flex items-center gap-1">
        <Input type="date" value={date} autoFocus className="h-8 w-[150px] text-xs"
          onChange={(e) => setDate(e.target.value)} />
        <Button size="sm" className="h-8 px-2 text-xs" disabled={!date || act.isPending}
          onClick={() => act.mutate(планирую
            ? { takenFor: date } : { deferUntil: date })}>
          {планирую ? 'Займусь' : 'Скрыть'}
        </Button>
        <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
          onClick={() => setPickingDate(null)}>Отмена</Button>
      </span>
    )
  }

  return (
    <span className="inline-flex shrink-0 items-center gap-0.5">
      {!compact && кнопкаДня}
      {!compact && кнопкаЗвезды}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="ghost" className="size-11 p-0 sm:h-8 sm:w-auto sm:px-2"
            aria-label="Личные действия" title="Как разложить у себя">
            <MoreHorizontal className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
            Только для вас: срок и состояние не меняются
          </DropdownMenuLabel>
          {compact && (
            <>
              <DropdownMenuItem onClick={() => act.mutate(inDay
                ? { dropDay: true }
                : { takenFor: workService.todayKey() })}>
                <Sun className="mr-2 h-3.5 w-3.5" />
                {inDay ? 'Убрать из моего дня' : 'Взять в мой день'}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => act.mutate({ starred: !mark?.starred })}>
                <Star className="mr-2 h-3.5 w-3.5" />
                {mark?.starred ? 'Снять важность' : 'Важно для меня'}
              </DropdownMenuItem>
            </>
          )}
          {/* Планирование: предмет остаётся на виду и встаёт на выбранный день.
              Стоит выше сокрытия намеренно — это обычный ответ на «когда», а
              прячут реже. */}
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <CalendarCheck className="mr-2 h-3.5 w-3.5" />
              {planned
                ? (planned === workService.todayKey() ? 'Займусь сегодня'
                  : `Займусь ${shortDay(planned)}`)
                : 'Займусь'}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem
                onClick={() => act.mutate({ takenFor: workService.todayKey() })}>
                Сегодня
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => act.mutate({ takenFor: завтра() })}>
                Завтра
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => act.mutate({ takenFor: nextWeekday(1) })}>
                В понедельник
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => { setDate(завтра()); setPickingDate('plan') }}>
                Выбрать день…
              </DropdownMenuItem>
              {planned && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => act.mutate({ dropDay: true })}>
                    Снять план
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          {/* Сокрытие: предмет уходит с глаз до даты. Названо тем, что делает, —
              прежнее «Не сегодня» звучало как планирование, а планированием не
              было. */}
          <DropdownMenuSub>
            {/* Просроченное не прячется: сервер откажет с объяснением, и
                предлагать заведомо отклонённое значит учить человека не верить
                меню. Причина стоит в подсказке — там, где её ищут. */}
            <DropdownMenuSubTrigger disabled={нельзяПрятать}
              title={нельзяПрятать
                ? 'Срок уже наступил: такое не прячется — его закрывают, '
                  + 'передают или переносят срок'
                : undefined}>
              <CalendarClock className="mr-2 h-3.5 w-3.5" />
              {нельзяПрятать ? 'Со сроком сегодня не прячется'
                : deferred ? `Скрыто до ${shortDay(deferred)}` : 'Не показывать до'}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem onClick={() => act.mutate({ deferUntil: завтра() })}>
                Завтра
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => act.mutate({ deferUntil: nextWeekday(1) })}>
                Понедельника
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => { setDate(завтра()); setPickingDate('defer') }}>
                Выбрать день…
              </DropdownMenuItem>
              {deferred && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => act.mutate({ undefer: true })}>
                    Вернуть сейчас
                  </DropdownMenuItem>
                </>
              )}
              {(mark?.defer_count ?? 0) >= 3 && (
                <>
                  <DropdownMenuSeparator />
                  {/* Счётчик меняет предложение, а не текст: повторять ту же
                      кнопку бессмысленно — отложенное трижды откладывают и
                      дальше. Наверх этот счётчик не уходит. */}
                  <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                    Откладывали {mark?.defer_count} раз. Может, перенести срок
                    или передать?
                  </DropdownMenuLabel>
                </>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          {/* Подборки перечислены сразу: их две-три, и подменю ради них стоило
              лишнего движения на каждое действие. */}
          <DropdownMenuLabel className="flex items-center gap-1.5 text-xs font-normal text-muted-foreground">
            <FolderPlus className="h-3.5 w-3.5" />В подборку
          </DropdownMenuLabel>
          {(lists.data?.lists ?? []).map((l) => (
            <DropdownMenuItem key={l.id} onClick={() => act.mutate({ listId: l.id })}>
              {l.name}
              {l.id === mark?.list_id && <span className="ml-auto text-xs">✓</span>}
            </DropdownMenuItem>
          ))}
          {(lists.data?.lists.length ?? 0) === 0 && (
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground/70">
              Подборок пока нет — заводятся в разделе «Моё»
            </DropdownMenuLabel>
          )}
          {mark?.list_id && (
            <DropdownMenuItem onClick={() => act.mutate({ dropList: true })}>
              Убрать из подборки «{listName}»
            </DropdownMenuItem>
          )}
          {mark && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => act.mutate({ clear: true })}>
                <X className="mr-2 h-3.5 w-3.5" />Убрать из раскладки
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </span>
  )
}

export default PlaceActions
