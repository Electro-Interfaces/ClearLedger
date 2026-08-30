/**
 * Общая доска: документы и поручения в одних колонках (этап 13д), три оси
 * группировки (этап 14).
 *
 * Доска одна, а колонки строятся из выбранной оси, и подпись говорит, что
 * делает перенос. Три отдельные доски разошлись бы на первой же правке
 * карточки, а одна доска с молчаливо разным смыслом переноса хуже трёх:
 * человек не может знать, меняет он предмет для всей компании или только у
 * себя.
 *
 * - **по состоянию** — колонки работы, перенос выполняет движок предмета
 *   (маршрут у поручения, круг виз у документа) и вправе отказать с причиной;
 * - **по моей раскладке** — колонки суть мои подборки, «Мой день» и
 *   «Отложено»; перенос меняет только `personal_marks`, никого не уведомляет
 *   и отказать не может по определению — это моя подборка;
 * - **по сроку** — горизонт работы; здесь перенос МЕНЯЕТ обязательство перед
 *   компанией, поэтому бросок принимают только колонки с однозначной датой.
 *
 * Отказ всегда с причиной. Карточка, молча прыгнувшая обратно, — загадка;
 * «у этого типа нет стадии в колонке „На согласовании“» — ответ, по которому
 * видно, что делать.
 *
 * Карточка на любой оси показывает корпоративное состояние и просрочку: личная
 * раскладка вправе менять порядок, но не вправе прятать правду о сроке.
 *
 * Перенос — нативный HTML5 drag-and-drop, как на доске поручений: новую
 * зависимость ради четырёх обработчиков не тянем.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { endOfWeek, format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { FileText, ListChecks, Loader2, RefreshCw, Star, Sun } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import * as workService from '@/services/workService'
import * as tasksService from '@/services/tasksService'
import type { WorkItem, WorkState } from '@/services/workService'
import { dt, PRIORITY_TONE, priorityWord } from '@/components/tasks/taskWords'
import { columnOf as колонкаПредмета, type BoardAxis } from '@/lib/boardAxis'
import { cn } from '@/lib/utils'

const BOARD_LIMIT = 200

const AXES: { code: BoardAxis; name: string; hint: string }[] = [
  {
    code: 'state',
    name: 'По состоянию',
    hint: 'Перенос выполняет движок предмета: маршрут у поручения, круг виз у документа.',
  },
  {
    code: 'place',
    name: 'По моей раскладке',
    hint: 'Видите только вы. Срок, состояние и просрочка не меняются.',
  },
  {
    code: 'due',
    name: 'По сроку',
    hint: 'Перенос меняет СРОК — обязательство перед компанией.',
  },
]

/** Колонка доски. Карточка стоит ровно в одной: карточка в двух колонках делает
 *  перенос загадкой «переместить или добавить». */
interface BoardColumn {
  code: string
  name: string
  /** Заполнено — колонка броска не принимает, и причина называется вслух. */
  refusal?: string
}

/** Конец рабочего дня, а не полночь: «до 3 сентября» человек понимает как
 *  «в течение третьего», и полночь делает срок вчерашним. Тот же расчёт, что в
 *  календаре рельсы. */
function endOfDay(on: Date): string {
  const d = new Date(on)
  d.setHours(18, 0, 0, 0)
  return d.toISOString()
}

export function WorkBoardPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [dragged, setDragged] = useState<WorkItem | null>(null)
  const [over, setOver] = useState<string | null>(null)

  const kind = params.get('kind') ?? ''
  const axis = (AXES.some((a) => a.code === params.get('axis'))
    ? params.get('axis') : 'state') as BoardAxis
  const set = (kv: Record<string, string | null>) => setParams((p) => {
    const next = new URLSearchParams(p)
    for (const [k, v] of Object.entries(kv)) { if (v) next.set(k, v); else next.delete(k) }
    return next
  }, { replace: true })

  const q = useQuery({
    queryKey: ['work-board', company.id, kind],
    queryFn: () => workService.listWork(company.id, {
      scope: 'open', kind: (kind || undefined) as 'doc' | 'task' | undefined,
      limit: BOARD_LIMIT, sort: 'due',
    }),
    placeholderData: keepPreviousData,
  })

  // Подборки нужны только личной оси, и запрос тот же, что у раскладки «Моего»:
  // react-query отдаёт их из общего кэша, второго обращения не случается.
  const lists = useQuery({
    queryKey: ['personal-lists', company.id],
    queryFn: () => workService.myLists(company.id),
    staleTime: 5 * 60 * 1000,
    enabled: axis === 'place',
  })

  const обновить = (ось: BoardAxis) => {
    void qc.invalidateQueries({ queryKey: ['work-board'] })
    void qc.invalidateQueries({ queryKey: ['work'] })
    void qc.invalidateQueries({ queryKey: ['work-mine'] })
    if (ось === 'state') void qc.invalidateQueries({ queryKey: ['work-summary'] })
    if (ось === 'place') {
      void qc.invalidateQueries({ queryKey: ['personal-lists', company.id] })
      void qc.invalidateQueries({ queryKey: ['placed'] })
    }
    if (ось === 'due') void qc.invalidateQueries({ queryKey: ['tasks'] })
  }

  const today = workService.todayKey()
  const завтра = useMemo(() => {
    const d = new Date()
    d.setDate(d.getDate() + 1)
    return workService.todayKey(d)
  }, [])
  const конецНедели = useMemo(
    () => workService.todayKey(endOfWeek(new Date(), { weekStartsOn: 1 })), [])

  const columns: BoardColumn[] = useMemo(() => {
    if (axis === 'state') {
      return (q.data?.columns ?? []).map((c) => ({ code: c.code, name: c.name }))
    }
    if (axis === 'place') {
      return [
        { code: 'day', name: 'Мой день' },
        ...(lists.data?.lists ?? []).map((l) => ({
          code: `list:${l.id}`, name: l.name,
        })),
        { code: 'loose', name: 'Не разложено' },
        {
          code: 'deferred',
          name: 'Отложено',
          // Откладывают ДО ДНЯ: «отложено» без даты — это забыто, а не
          // отложено. Броском день не назвать, поэтому колонка только на выход.
          refusal: 'Откладывают до дня — «Не сегодня» в строке работы. Вынести отсюда можно броском.',
        },
      ]
    }
    return [
      {
        code: 'overdue',
        name: 'Просрочено',
        refusal: 'Просроченное броском не переносят: срок продлевают в карточке или точным числом в календаре справа.',
      },
      { code: 'today', name: 'Сегодня' },
      { code: 'tomorrow', name: 'Завтра' },
      {
        code: 'week',
        name: 'На этой неделе',
        refusal: 'Неделя — не дата. Точное число ставят броском в календарь справа.',
      },
      {
        code: 'later',
        name: 'Позже',
        refusal: '«Позже» — не дата. Точное число ставят броском в календарь справа.',
      },
      {
        code: 'none',
        name: 'Без срока',
        refusal: 'Бросок срок ставит, а не отменяет: снимают его в карточке.',
      },
    ]
  }, [axis, q.data?.columns, lists.data?.lists])

  /** В какой колонке стоит карточка. Правило старшинства живёт в `boardAxis` и
   *  проверяется перебором: карточка обязана попадать ровно в одну колонку, а
   *  ломается это молча. */
  const columnOf = useMemo(() => {
    const горизонт = {
      today, tomorrow: завтра, weekEnd: конецНедели,
      lists: new Set((lists.data?.lists ?? []).map((l) => l.id)),
    }
    return (i: WorkItem) => колонкаПредмета(axis, i, горизонт)
  }, [axis, lists.data?.lists, today, завтра, конецНедели])

  /** Принимает ли колонка именно эту карточку. Считается ДО броска, чтобы
   *  колонка не подсвечивалась приглашением к тому, чего не будет. */
  const отказ = (col: BoardColumn, item: WorkItem): string | null => {
    if (col.refusal) return col.refusal
    if (axis === 'due' && item.kind === 'doc') {
      return 'Срок документа так не двигается: у него своя регистрация и согласование — меняйте в карточке.'
    }
    return null
  }

  const move = useMutation({
    mutationFn: async ({ item, col }: { item: WorkItem; col: BoardColumn }) => {
      if (axis === 'state') {
        return workService.moveWork(item.kind, item.id, company.id, col.code as WorkState)
      }
      if (axis === 'place') {
        const ref = workService.targetRef(item)
        if (col.code === 'day') return workService.place(company.id, ref, { takenFor: today })
        // «Не разложено» — снять день, подборку и сокрытие, но НЕ саму отметку:
        // вместе с ней ушли бы звезда и счётчик откладываний, а человек их не
        // трогал. Стереть отметку целиком по-прежнему можно из меню строки.
        if (col.code === 'loose') {
          return workService.place(company.id, ref,
            { dropList: true, dropDay: true, undefer: true })
        }
        // Из подборки в подборку — перенос, а не добавление: подборка
        // эксклюзивна. День и сокрытие снимаются вместе с ней, иначе карточка
        // осталась бы стоять в старшей колонке и бросок ничего бы не показал.
        return workService.place(company.id, ref, {
          listId: col.code.slice('list:'.length), dropDay: true, undefer: true,
        })
      }
      const on = new Date()
      if (col.code === 'tomorrow') on.setDate(on.getDate() + 1)
      return tasksService.taskAction(item.id, { companyId: company.id, dueAt: endOfDay(on) })
    },
    onSuccess: (_r, v) => {
      обновить(axis)
      if (axis === 'due') {
        const on = new Date()
        if (v.col.code === 'tomorrow') on.setDate(on.getDate() + 1)
        toast.success(`Срок — ${format(on, 'd MMMM', { locale: ru })}`)
      }
    },
    // Причина отказа — главное, что человек должен увидеть: иначе карточка
    // просто вернулась на место, и почему — неизвестно.
    onError: (e) => toast.error((e as Error).message, { duration: 6000 }),
  })

  const items = q.data?.work ?? []

  const drop = (col: BoardColumn) => {
    const item = dragged
    setDragged(null); setOver(null)
    if (!item || columnOf(item) === col.code) return
    const причина = отказ(col, item)
    if (причина) { toast.error(причина, { duration: 6000 }); return }
    move.mutate({ item, col })
  }

  const подпись = AXES.find((a) => a.code === axis)!

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto">
          <h1 className="text-lg font-semibold">Доска работы</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Колонки общие для документов и поручений. {подпись.hint}
          </p>
        </div>
        <Select value={axis} onValueChange={(v) => set({ axis: v === 'state' ? null : v })}>
          <SelectTrigger className="h-8 w-[190px] text-xs">
            <SelectValue placeholder="Ось" />
          </SelectTrigger>
          <SelectContent>
            {AXES.map((a) => (
              <SelectItem key={a.code} value={a.code}>{a.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={kind || 'all'}
          onValueChange={(v) => set({ kind: v === 'all' ? null : v })}>
          <SelectTrigger className="h-8 w-[150px] text-xs">
            <SelectValue placeholder="Род" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Всё вместе</SelectItem>
            <SelectItem value="doc">Документы</SelectItem>
            <SelectItem value="task">Поручения</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" className="h-8"
          onClick={() => void q.refetch()} disabled={q.isFetching}>
          <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', q.isFetching && 'animate-spin')} />
          Обновить
        </Button>
      </div>

      {q.isLoading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Собираем доску…
        </div>
      ) : q.isError ? (
        <QueryError message="Доска не загрузилась" error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
          {columns.map((col) => {
            const cards = items.filter((i) => columnOf(i) === col.code)
            const droppable = !!dragged && columnOf(dragged) !== col.code
              && !отказ(col, dragged)
            return (
              // `data-col` — единственный способ проверить перенос: настоящий
              // drag браузер запускает своим механизмом, до которого прогон не
              // дотягивается мышью, и события приходится слать руками — по
              // адресуемой колонке.
              <div key={col.code} data-col={col.code}
                onDragOver={(e) => { e.preventDefault(); setOver(col.code) }}
                onDragLeave={() => setOver((c) => (c === col.code ? null : c))}
                onDrop={() => drop(col)}
                className={cn(
                  'flex w-[280px] shrink-0 flex-col rounded-xl border bg-muted/30 transition-colors',
                  over === col.code && droppable
                    && 'border-primary bg-primary/5 ring-1 ring-primary/30')}>
                <div className="flex items-center gap-2 px-3 py-2.5">
                  <span className="text-[13px] font-medium">{col.name}</span>
                  <span className={cn('ml-auto rounded-full px-1.5 py-0.5 text-xs tabular-nums',
                    cards.length ? 'bg-background text-muted-foreground'
                      : 'text-muted-foreground/50')}>
                    {cards.length}
                  </span>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
                  {cards.map((item) => (
                    <Card key={`${item.kind}-${item.id}`} item={item}
                      showState={axis !== 'state'}
                      dragging={dragged?.id === item.id}
                      onDragStart={() => setDragged(item)}
                      onDragEnd={() => { setDragged(null); setOver(null) }}
                      onOpen={() => navigate(workService.workHref(item))} />
                  ))}
                  {cards.length === 0 && (
                    <div className="px-2 py-6 text-center text-xs text-muted-foreground/70">
                      Пусто
                    </div>
                  )}
                </div>
              </div>
            )
          })}
          {axis === 'place' && (lists.data?.lists.length ?? 0) === 0 && (
            <div className="w-[280px] shrink-0 self-start rounded-xl border border-dashed p-3 text-xs text-muted-foreground">
              Подборок пока нет — заводятся в разделе «Моё». Пока их нет, доска
              раскладки показывает только день и отложенное.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Card({ item, dragging, showState, onDragStart, onDragEnd, onOpen }: {
  item: WorkItem; dragging: boolean
  /** На чужой оси состояние показывается словом: личная раскладка вправе менять
   *  порядок, но не вправе прятать, что виза горит третий день. */
  showState: boolean
  onDragStart: () => void; onDragEnd: () => void; onOpen: () => void
}) {
  const Icon = item.kind === 'doc' ? FileText : ListChecks
  const вДне = item.mark?.taken_for === workService.todayKey()
  return (
    <div draggable onDragStart={onDragStart} onDragEnd={onDragEnd} onClick={onOpen}
      className={cn('group cursor-grab rounded-lg border bg-card px-2.5 py-2 text-xs shadow-sm transition-all active:cursor-grabbing',
        'hover:-translate-y-px hover:border-primary/40 hover:shadow-md',
        dragging && 'opacity-40 shadow-none',
        item.overdue && 'border-red-500/40 bg-red-500/5')}>
      <div className="flex items-start gap-1.5">
        <Icon className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground"
          aria-label={item.kind === 'doc' ? 'документ' : 'поручение'} />
        <span className="flex-1 font-medium leading-snug">{item.title}</span>
        <span className="shrink-0 font-mono text-xs text-muted-foreground/70">
          {item.key}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
        {/* Приоритет словом, а не цветом заголовка: карточка на доске и так
            читается сверху вниз, и окрашенное название спорит с состоянием. */}
        {item.priority && priorityWord(item.priority) && (
          <span className={PRIORITY_TONE[item.priority]}>
            {priorityWord(item.priority)}
          </span>
        )}
        {showState && (
          <span className="rounded bg-muted px-1 py-px">{item.state_name}</span>
        )}
        {item.stage && item.stage !== item.state_name && <span>{item.stage}</span>}
        {item.responsible && <span>{item.responsible}</span>}
        {item.due_at && (
          <span className={cn(item.overdue && 'text-red-600 dark:text-red-400')}>
            {dt(item.due_at)}
          </span>
        )}
        {вДне && (
          <Sun className="h-3 w-3 fill-current text-amber-600 dark:text-amber-400"
            aria-label="в моём дне" />
        )}
        {item.mark?.starred && (
          <Star className="h-3 w-3 fill-current text-amber-600 dark:text-amber-400"
            aria-label="важно для меня" />
        )}
      </div>
    </div>
  )
}

export default WorkBoardPage
