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
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, FolderPlus, MoreHorizontal, Star, Sun, X } from 'lucide-react'
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
import { cn } from '@/lib/utils'

/** Ближайший день недели вперёд: «в понедельник» — самый частый ответ на
 *  вопрос «когда вернуться», и считать его человеку не должно приходиться. */
function nextWeekday(target: number): string {
  const d = new Date()
  d.setDate(d.getDate() + ((target - d.getDay() + 7) || 7))
  return workService.todayKey(d)
}

const завтра = () => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return workService.todayKey(d)
}

export function PlaceActions({ companyId, targetRef, mark, onChanged, compact }: {
  companyId: string
  targetRef: string
  mark: PersonalMark | null | undefined
  onChanged: () => void
  /** В плотных списках звезда и день прячутся в меню. */
  compact?: boolean
}) {
  const qc = useQueryClient()
  const [pickingDate, setPickingDate] = useState(false)
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
      setPickingDate(false)
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

  const inDay = mark?.taken_for === workService.todayKey()
  const deferred = mark?.deferred_until ?? null
  const listName = lists.data?.lists.find((l) => l.id === mark?.list_id)?.name

  const кнопкаДня = (
    <Button size="sm" variant="ghost" disabled={act.isPending}
      className={cn('h-8 px-2', inDay && 'text-amber-600 dark:text-amber-400')}
      title={inDay ? 'Убрать из моего дня' : 'Взять в мой день'}
      onClick={() => act.mutate(inDay
        ? { dropDay: true }
        : { takenFor: workService.todayKey() })}>
      <Sun className={cn('h-3.5 w-3.5', inDay && 'fill-current')} />
    </Button>
  )

  const кнопкаЗвезды = (
    <Button size="sm" variant="ghost" disabled={act.isPending}
      className={cn('h-8 px-2', mark?.starred && 'text-amber-600 dark:text-amber-400')}
      title={mark?.starred ? 'Снять важность' : 'Важно для меня'}
      onClick={() => act.mutate({ starred: !mark?.starred })}>
      <Star className={cn('h-3.5 w-3.5', mark?.starred && 'fill-current')} />
    </Button>
  )

  if (pickingDate) {
    return (
      <span className="inline-flex items-center gap-1">
        <Input type="date" value={date} autoFocus className="h-8 w-[150px] text-xs"
          onChange={(e) => setDate(e.target.value)} />
        <Button size="sm" className="h-8 px-2 text-xs" disabled={!date || act.isPending}
          onClick={() => act.mutate({ deferUntil: date })}>Скрыть</Button>
        <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
          onClick={() => setPickingDate(false)}>Отмена</Button>
      </span>
    )
  }

  return (
    <span className="inline-flex shrink-0 items-center gap-0.5">
      {!compact && кнопкаДня}
      {!compact && кнопкаЗвезды}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="ghost" className="h-8 px-2"
            title="Как разложить у себя">
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
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <CalendarClock className="mr-2 h-3.5 w-3.5" />
              {deferred ? `Скрыто до ${deferred}` : 'Не сегодня'}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem onClick={() => act.mutate({ deferUntil: завтра() })}>
                До завтра
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => act.mutate({ deferUntil: nextWeekday(1) })}>
                До понедельника
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => { setDate(завтра()); setPickingDate(true) }}>
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
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <FolderPlus className="mr-2 h-3.5 w-3.5" />
              {listName ? `В подборке «${listName}»` : 'В мою подборку'}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {(lists.data?.lists ?? []).map((l) => (
                <DropdownMenuItem key={l.id} onClick={() => act.mutate({ listId: l.id })}>
                  {l.name}
                  {l.id === mark?.list_id && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
              ))}
              {(lists.data?.lists.length ?? 0) === 0 && (
                <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                  Подборок пока нет — заводятся в разделе «Моё»
                </DropdownMenuLabel>
              )}
              {mark?.list_id && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => act.mutate({ dropList: true })}>
                    Убрать из подборки
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
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
