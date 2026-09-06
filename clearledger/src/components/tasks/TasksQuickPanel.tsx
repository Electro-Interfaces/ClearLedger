/**
 * Окно «Трека» из шапки — пульт работы, а не сводка.
 *
 * В шапку заглядывают не за отчётом: посмотреть, что горит, отметить сделанное,
 * записать новое, пока не забылось, и увидеть свой день целиком. Поэтому окно
 * повторяет устройство рабочего места «Моё»: слева разрезы со счётчиками, в
 * центре список выбранного, справа день — взятое, напоминания, встречи.
 *
 * Почему не четыре вкладки, как было: вкладки знали только поручения, а «Трек»
 * ведёт документы и поручения вместе. Виза и ознакомление — такая же работа на
 * человеке, и не показывать их в пульте значило заставлять открывать приложение
 * ради вопроса «что от меня ждут».
 *
 * Списки не пишутся заново: очередь — та же `MyWorkPage`, разложенное — тот же
 * `PlacedList`, что на экранах приложения. Второй экземпляр строки разошёлся бы
 * с первым на первой же правке: действие в строке, пустое состояние, цвет
 * просрочки.
 *
 * Что сюда НЕ тащим: маршруты и стадии целиком, историю, отборы по меткам и
 * объектам, командную строку над пачкой, доски и планирование. Это работа на
 * весь экран, и она живёт в «Треке» — кнопка ведёт ровно в открытый разрез.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpRight, Bell, BookOpen, CalendarDays, Check, ChevronDown, Clock3, Eye, FileText,
  Flame, ListChecks, Loader2, Plus, Star, Stamp, Users,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useSupportContext } from '@/contexts/SupportContext'
import * as tasksService from '@/services/tasksService'
import * as workService from '@/services/workService'
import type { SpaceTask } from '@/services/tasksService'
import { DOCS_VIEWS } from '@/pages/docs/DocsLayout'
import { MyWorkPage } from '@/pages/docs/MyWorkPage'
import { PlacedList } from '@/components/docs/PlacedList'
import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSectionOpen } from '@/hooks/useSectionOpen'
import { SearchPicker } from '@/components/tasks/SearchPicker'
import { workCounts } from '@/lib/workCounts'

/** Срок словами: «сегодня» / «завтра» / «просрочена на 3 дн» — точная дата тут лишняя. */
function dueText(due: string | null, overdue: boolean): string | null {
  if (!due) return null
  const days = Math.round((new Date(due).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000)
  if (days < 0) return `просрочена на ${-days} дн`
  // Срок сегодня, но час уже прошёл: бэкенд пометил задачу просроченной, а разница
  // в днях ещё ноль — «просрочена на 0 дн» тут и вылезала.
  if (overdue) return 'срок истёк'
  if (days === 0) return 'срок сегодня'
  if (days === 1) return 'срок завтра'
  return `срок через ${days} дн`
}

/** Час и минута события: «11:00». */
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString('ru-RU', {
  hour: '2-digit', minute: '2-digit',
})

type ViewKey = string

/** Иконка разреза. Слова, порядок и группы берём из меню «Трека»
 *  (`DOCS_VIEWS`), здесь остаётся только картинка: в меню приложения иконок
 *  нет, а в пульте они помогают попасть в нужную строку с одного взгляда. */
const VIEW_ICONS: Record<string, typeof Flame> = {
  today: Flame,
  starred: Star,
  deferred: Clock3,
  'mine-all': ListChecks,
  approvals: Stamp,
  acquaints: BookOpen,
  errands: Check,
  mine: FileText,
  assigned: Users,
  watching: Eye,
}

/** «Сегодня» в приложении — экран дня целиком. В окне день стоит отдельной
 *  полосой справа, поэтому в центре показывается то, что на сегодня давит:
 *  подсказку меню здесь пришлось бы читать как обещание, которого окно не даёт. */
const VIEW_HINTS: Record<string, string> = {
  today: 'просрочено и срок сегодня; день целиком — полосой справа',
}

/** Разрезы рельсы — ровно пункты раздела «Моё» приложения, в том же порядке и
 *  с теми же группами. Свой перечень здесь уже расходился с меню: «Поручения»
 *  стояли в «Ждут от меня», а «Я поставил» — в «Веду сам», хотя в приложении
 *  они давно в «Веду сам» и «Слежу». Человек, переходя из окна на экран, искал
 *  знакомый разрез не там, где он есть.
 *
 *  Скрытые пункты (календарь, записи, подборки) не берём: календарь и записи
 *  живут в правой рельсе, подборки — работа на весь экран. */
const VIEWS: {
  key: ViewKey; label: string; hint: string; group: string
  icon: typeof Flame; href: string
}[] = (DOCS_VIEWS['/docs/work'] ?? [])
  .filter((v) => !v.hidden)
  .map((v) => ({
    key: v.key,
    label: v.label,
    hint: VIEW_HINTS[v.key] ?? v.hint,
    // Первые три пункта — личная раскладка, и заголовка над ними в приложении
    // нет намеренно. Пустая строка группы сохраняет это и здесь.
    group: v.group ?? '',
    icon: VIEW_ICONS[v.key] ?? ListChecks,
    href: `/docs/work?view=${v.key}`,
  }))

/** Ключ числа у разреза — тот же `badge`, что в меню приложения. */
const BADGE_OF: Record<string, string> = Object.fromEntries(
  (DOCS_VIEWS['/docs/work'] ?? []).filter((v) => v.badge).map((v) => [v.key, v.badge!]))

/** Порядок групп — тот же, что в меню: он и есть смысл раскладки. */
const GROUPS = VIEWS.reduce<string[]>((acc, v) => (
  acc.includes(v.group) ? acc : [...acc, v.group]), [])

/** Ширина полосы, которую человек тянет мышью, с памятью между сессиями.
 *
 *  Отдельного компонента-сплиттера в проекте нет — тот же приём написан в правом
 *  доке; заводить общий ради двух ручек было бы больше кода, чем самих ручек.
 *  Ширина в пикселях, а не в долях: полосы несут списки с номерами и датами, и
 *  при смене окна им важнее сохранить читаемость, чем пропорцию. */
function useDragWidth(key: string, initial: number, min: number, max: number) {
  const [width, setWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem(key))
    return saved >= min && saved <= max ? saved : initial
  })
  const draggingRef = useRef<((e: MouseEvent) => number) | null>(null)

  const start = useCallback((measure: (e: MouseEvent) => number) =>
    (e: React.MouseEvent) => {
      e.preventDefault()
      draggingRef.current = measure
      document.body.style.userSelect = 'none'
      document.body.style.cursor = 'col-resize'
    }, [])

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const measure = draggingRef.current
      if (!measure) return
      setWidth(Math.min(max, Math.max(min, measure(e))))
    }
    const onUp = () => {
      if (!draggingRef.current) return
      draggingRef.current = null
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      localStorage.setItem(key, String(width))
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [key, min, max, width])

  // Стрелками — тот же шаг, что мышью: полоса, которую нельзя подвинуть с
  // клавиатуры, для части людей просто не двигается.
  const nudge = useCallback((delta: number) => {
    setWidth((w) => {
      const next = Math.min(max, Math.max(min, w + delta))
      localStorage.setItem(key, String(next))
      return next
    })
  }, [key, min, max])

  return { width, start, nudge }
}

/** Вертикальный разделитель полос: тонкая линия, широкая зона захвата. */
function Grip({ label, onMouseDown, onNudge }: {
  label: string
  onMouseDown: (e: React.MouseEvent) => void
  onNudge: (delta: number) => void
}) {
  return (
    <div role="separator" aria-orientation="vertical" aria-label={label} tabIndex={0}
      onMouseDown={onMouseDown}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') { e.preventDefault(); onNudge(-16) }
        if (e.key === 'ArrowRight') { e.preventDefault(); onNudge(16) }
      }}
      className="group relative hidden w-1 shrink-0 cursor-col-resize md:block focus-visible:outline-none">
      <span className="absolute inset-y-0 -left-1 -right-1" />
      <span className="absolute inset-y-0 left-0 w-px bg-border transition-colors group-hover:bg-primary group-focus-visible:bg-primary" />
    </div>
  )
}


export function TasksQuickPanel({ compact: compactProp }: {
  /** Правый док узкий: рельса и день туда не помещаются, остаётся список с
   *  разрезами строкой поверх. */
  compact?: boolean
} = {}) {
  // На телефоне компактная раскладка включается сама (замечание МАГа 06.09.2026):
  // окно взаимодействия открывало «Трек» тремя полосами — рельса разрезов, список и
  // полоса дня, — и на 353 px от них оставались обрезанные надписи «ЖДУ…», «ВЕДУ…»,
  // а низ окна занимал «Мой день» вместо самой работы.
  const isMobile = useIsMobile()
  const compact = compactProp ?? isMobile
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { companyId } = useCompany()
  const { user } = useAuth()
  const me = user?.id ?? ''
  const { closeInteraction } = useSupportContext()
  const [view, setView] = useState<ViewKey>(VIEWS[0]?.key ?? 'today')
  // Ширины полос человек ставит сам: у кого-то рельса с длинными словами, у
  // кого-то день с длинными названиями встреч. Значения переживают перезагрузку.
  const shellRef = useRef<HTMLDivElement>(null)
  const rail = useDragWidth('cl-track-rail-w', 224, 160, 420)
  const day = useDragWidth('cl-track-day-w', 320, 220, 560)
  const [draft, setDraft] = useState('')
  // Кому: пусто — себе. Список тот же, что в карточке поручения, и тем же ключом
  // запроса: открыв «Трек» следом, человек не ждёт второй загрузки сотрудников.
  const [assigneeId, setAssigneeId] = useState('')
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60 * 1000,
  })
  const people = peopleQ.data?.people ?? []

  // Очередь целиком — один запрос на все шесть разрезов «Ждут от меня» и на их
  // счётчики. Пункт, который считает себя сам, — это шесть запросов на открытие.
  const mineQ = useQuery({
    queryKey: ['work-mine', companyId],
    queryFn: () => workService.myWork(companyId),
    enabled: !!companyId,
  })
  const listsQ = useQuery({
    // Тот же ключ, что у экранов подборок: два ключа на один список означают,
    // что правка в пульте не видна на экране и наоборот.
    queryKey: ['personal-lists', companyId],
    queryFn: () => workService.myLists(companyId),
    enabled: !!companyId,
    staleTime: 60 * 1000,
  })
  const assignedQ = useQuery({
    queryKey: ['tasks', companyId, 'assigned', '', '', ''],
    queryFn: () => tasksService.listTasks(companyId, 'assigned'),
    enabled: !!companyId,
  })
  const watchingQ = useQuery({
    queryKey: ['tasks', companyId, 'watching', '', '', ''],
    queryFn: () => tasksService.listTasks(companyId, 'watching'),
    enabled: !!companyId,
  })

  // Тот же расчёт, что у меню «Трека» (`lib/workCounts`), и те же ключи
  // запросов: числа под одним словом в окне и в меню обязаны совпадать, иначе
  // одному из двух мест человек перестаёт верить. Раньше окно считало «Я
  // поставил» по странице (сто строк), а меню — по `total` сервера.
  const счёт = useMemo(() => workCounts({
    mine: mineQ.data, lists: listsQ.data,
    assigned: assignedQ.data, watching: watchingQ.data,
  }), [mineQ.data, assignedQ.data, watchingQ.data, listsQ.data])

  /** Число разреза: ключ бейджа тот же, что в меню приложения. */
  const счётчик = (key: ViewKey) => счёт[BADGE_OF[key] ?? ''] ?? 0

  const overdue = счёт.overdue

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['tasks'] })
    void qc.invalidateQueries({ queryKey: ['work-mine'] })
    void qc.invalidateQueries({ queryKey: ['placed'] })
  }

  // Быстрая постановка — строкой и без срока: окно в шапке существует ровно для того,
  // чтобы мысль не потерялась. Себе или коротким поручением соседу — выбор рядом со
  // строкой; тип, проект и срок проставляются потом в карточке, куда уводит уведомление.
  // «Себе» — это ЯВНЫЙ исполнитель, а не пустое поле: задача без исполнителя ничья,
  // и в «Моей очереди» (отбор идёт по исполнителю) она не появлялась вовсе.
  const add = useMutation({
    mutationFn: () => tasksService.createTask({
      companyId, title: draft.trim(), assigneeId: assigneeId || me || undefined,
    }),
    onSuccess: (t: SpaceTask) => {
      setDraft('')
      const to = people.find((p) => p.id === assigneeId)
      // Поручение чужому уходит из моей очереди — без перехода в «Я поставил»
      // окно выглядело бы так, будто ничего не произошло.
      if (to) setView('assigned')
      toast.success(to
        ? `${tasksService.taskKey(t)} — поручено: ${to.name}`
        : `Задача ${tasksService.taskKey(t)} поставлена`, {
        action: { label: 'Открыть', onClick: () => openTask(t.id) },
      })
      refresh()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const go = (href: string) => { closeInteraction(); navigate(href) }
  // Карточку поручения открывает реестр «Компании» — только он читает `?task=`.
  // Раздел «Моё» показывает работу НА МНЕ строками, и поручение, отданное
  // другому, там не появится вовсе: переход из окна вёл на список, в котором
  // искомого нет, и выглядел как «кнопка ничего не сделала».
  const openTask = (id: string) => go(`/docs/company?view=errands&task=${id}`)
  const current = VIEWS.find((v) => v.key === view) ?? VIEWS[0]

  const renderView = (v: typeof VIEWS[number]) => {
    const Icon = v.icon
    const n = счётчик(v.key)
    const active = v.key === view
    return (
      <button key={v.key} type="button" title={v.hint}
        onClick={() => setView(v.key)}
        aria-current={active ? 'page' : undefined}
        className={cn('flex items-center gap-2 rounded-md text-sm transition-colors',
          compact ? 'shrink-0 px-2.5 py-1' : 'w-full px-2 py-1.5 text-left',
          active ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
        <Icon className="size-4 shrink-0" />
        <span className={cn('truncate', compact ? '' : 'flex-1')}>{v.label}</span>
        {n > 0 && (
          <span className={cn('shrink-0 tabular-nums text-xs',
            active ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
            {n}
          </span>
        )}
      </button>
    )
  }

  const railNav = (
    <nav aria-label="Разрезы работы"
      style={compact ? undefined : { width: rail.width }}
      className={cn(compact
        ? 'flex shrink-0 gap-1 overflow-x-auto border-b border-border/60 px-3 py-2'
        : 'shrink-0 space-y-3 overflow-y-auto p-3')}>
      {GROUPS.map((group) => {
        const views = VIEWS.filter((v) => v.group === group)
        // Полоса разрезов на телефоне идёт строкой без заголовков — сворачивать
        // там нечего.
        if (compact) return <div key={group} className="contents">{views.map(renderView)}</div>
        return (
          <RailGroup key={group} title={group}
            count={views.reduce((n, v) => n + счётчик(v.key), 0)}>
            {views.map(renderView)}
          </RailGroup>
        )
      })}
    </nav>
  )

  return (
    <div className="flex h-full flex-col">
      {/* Постановка стоит над всем окном, а не внутри разреза: записать мысль
          человек приходит независимо от того, какой список сейчас открыт. */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-2">
        <Plus className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <Input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={300}
          placeholder={assigneeId ? 'Что поручить — Enter поставит' : 'Записать задачу себе — Enter поставит'}
          className="h-8 min-w-40 flex-1 border-0 bg-transparent px-0 text-sm shadow-none focus-visible:ring-0"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim().length >= 3 && !add.isPending) add.mutate()
          }} />
        {/* Кому — рядом со строкой, а не в карточке: короткое поручение соседу
            («посмотри счёт», «позвони подрядчику») не стоит целого экрана.
            Поле нарисовано рамкой, а не подсказкой в цвет фона: прозрачный
            селектор у края строки человек просто не находит глазом. */}
        {/* Кому — с поиском и разбивкой на своих и сторонних (просьба МАГа 06.09.2026):
            людей в пространстве десятки, внешних участников будет больше, и выбирать
            их прокруткой длинного списка нельзя. Пикер тот же, что у объектов и
            номенклатуры, — набрал буквы, увидел строку. */}
        <span className="flex min-w-0 shrink-0 items-center gap-1.5">
          <span className="text-xs text-muted-foreground">кому</span>
          <SearchPicker items={people.map((p) => ({ id: p.id, name: p.name, party: p.partyType }))}
            value={assigneeId} onChange={setAssigneeId}
            placeholder="себе" emptyLabel="себе" searchPlaceholder="Найти сотрудника…"
            disabled={!peopleQ.isSuccess} loading={peopleQ.isLoading}
            groupByParty className="w-[11rem] text-sm" width="w-[16rem]" />
        </span>
        {/* Почему кнопка бывает неактивна — сказано подсказкой: раньше человек
            нажимал и не понимал, чего от него хотят (замечание МАГа 06.09.2026). */}
        <Button size="sm" className="h-8 shrink-0"
          disabled={draft.trim().length < 3 || add.isPending}
          title={draft.trim().length < 3
            ? 'Впишите, что нужно сделать, — не короче трёх букв'
            : (assigneeId ? 'Поручить выбранному сотруднику' : 'Записать задачу себе')}
          onClick={() => add.mutate()}>
          {add.isPending
            ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            : <Plus className="mr-1.5 h-3.5 w-3.5" />}
          {assigneeId ? 'Поручить' : 'Поставить'}
        </Button>
      </div>

      <div ref={shellRef} className="flex min-h-0 flex-1 flex-col md:flex-row">
        {railNav}
        {!compact && (
          <Grip label="Ширина списка разрезов" onNudge={rail.nudge}
            onMouseDown={rail.start((e) => {
              const box = shellRef.current?.getBoundingClientRect()
              return box ? e.clientX - box.left : rail.width
            })} />
        )}

        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-2">
            <div className="min-w-0">
              <h2 className="truncate text-sm font-medium text-foreground">{current.label}</h2>
              <p className="truncate text-xs text-muted-foreground">{current.hint}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {overdue > 0 && (
                <span className="text-xs font-medium text-red-600 dark:text-red-400">
                  просрочено {overdue}
                </span>
              )}
              <Button size="sm" variant="outline" className="h-8 gap-1.5"
                onClick={() => go(current.href)}>
                Открыть «Трек»
                <ArrowUpRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <ViewBody view={view} companyId={companyId}
              tasks={view === 'assigned' ? assignedQ.data?.tasks : watchingQ.data?.tasks}
              loading={view === 'assigned' ? assignedQ.isLoading : watchingQ.isLoading}
              onOpen={openTask} onChanged={refresh} />
          </div>
        </section>

        {!compact && (
          <>
            <Grip label="Ширина полосы дня" onNudge={(d) => day.nudge(-d)}
              onMouseDown={day.start((e) => {
                const box = shellRef.current?.getBoundingClientRect()
                return box ? box.right - e.clientX : day.width
              })} />
            <DayAside companyId={companyId} onOpen={go} width={day.width} />
          </>
        )}
      </div>
    </div>
  )
}

/**
 * Группа разрезов в рельсе: заголовок сворачивает свой список (просьба МАГа
 * 06.09.2026). Разрезов тринадцать, и «Ждут от меня» с «Веду сам» человеку нужны
 * не одновременно; свёрнутая группа показывает, сколько в ней работы, чтобы её не
 * приходилось открывать ради счёта. Что открыто — помним, как и строки каталога.
 *
 * У личной раскладки (Сегодня · Важное · Отложено) заголовка нет — как и в меню
 * приложения: всякое название здесь оказывалось жаргоном, а начинают работу
 * именно с неё, и сворачивать её незачем.
 */
function RailGroup({ title, count, children }: {
  title: string; count: number; children: React.ReactNode
}) {
  const [open, toggle] = useSectionOpen(`track.${title}`, true)
  if (!title) return <div className="space-y-0.5">{children}</div>
  return (
    <div className="space-y-0.5">
      <button type="button" onClick={toggle} aria-expanded={open}
        className="flex min-h-8 w-full items-center gap-1.5 px-2 text-left text-xs font-semibold
                   uppercase tracking-wide text-muted-foreground transition-colors
                   hover:text-foreground">
        <ChevronDown className={cn('size-3 shrink-0 transition-transform', open ? '' : '-rotate-90')} />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {count > 0 && <span className="shrink-0 tabular-nums font-normal">{count}</span>}
      </button>
      {open && children}
    </div>
  )
}

/** Содержимое выбранного разреза. Очередь и разложенное берём готовыми экранами
 *  приложения — здесь только выбор, что показать. */
function ViewBody({ view, companyId, tasks, loading, onOpen, onChanged }: {
  view: ViewKey; companyId: string
  tasks?: SpaceTask[]; loading: boolean
  onOpen: (id: string) => void; onChanged: () => void
}) {
  switch (view) {
    // Ключи — те же, что в меню приложения: `today`, `mine-all`, `mine`.
    // Свои имена («горит», «очередь», «моё») окно уже носило, и разрез в нём
    // назывался не так, как тот же разрез на экране.
    case 'today':
      return <MyWorkPage buckets={['overdue', 'today']} heading={false} hideDeferred
        empty="На сегодня ничего не горит: сроки не поджимают." />
    case 'mine-all':
      return <MyWorkPage heading={false} />
    case 'approvals':
      return <MyWorkPage reasons={['approve']} heading={false}
        empty="Виз на вас нет." />
    case 'acquaints':
      return <MyWorkPage reasons={['acquaint']} heading={false}
        empty="Ознакомиться пока не с чем." />
    case 'errands':
      return <MyWorkPage reasons={['do']} heading={false}
        empty="Поручений на вас нет." />
    case 'mine':
      return <MyWorkPage reasons={['own']} heading={false}
        empty="Документов, где вы автор или ответственный, сейчас нет." />
    case 'starred':
      return <PlacedList companyId={companyId} scope="starred" onChanged={onChanged}
        empty="Ничего не помечено. Звёздочка ставится в строке работы." />
    case 'deferred':
      return <PlacedList companyId={companyId} scope="deferred" onChanged={onChanged}
        empty="Отложенного нет. Отложить можно в строке очереди — срок компании при этом не меняется." />
    default:
      return <TaskLines rows={tasks} loading={loading} view={view} onOpen={onOpen}
        onChanged={onChanged} companyId={companyId} />
  }
}

/** Поручения, поставленные другим, и то, за чем человек следит со стороны. */
function TaskLines({ rows, loading, view, companyId, onOpen, onChanged }: {
  rows?: SpaceTask[]; loading: boolean; view: ViewKey; companyId: string
  onOpen: (id: string) => void; onChanged: () => void
}) {
  const list = useMemo(
    () => (rows ?? []).filter((t) => view !== 'assigned' || t.status === 'open'),
    [rows, view])

  const done = useMutation({
    mutationFn: (id: string) => tasksService.taskAction(id, { companyId, status: 'done' }),
    onSuccess: () => { toast.success('Задача закрыта'); onChanged() },
    onError: (e) => toast.error((e as Error).message),
  })

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Собираем список…
      </div>
    )
  }
  if (list.length === 0) {
    return (
      <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
        {view === 'assigned'
          ? 'Вы пока никому ничего не поручали.'
          : 'Вы ни за чем не следите со стороны.'}
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded-lg border">
      {list.map((t) => (
        <div key={t.id}
          className="group flex items-start gap-2 border-b border-border/60 px-3 py-2 transition-colors last:border-0 hover:bg-accent">
          {/* Закрыть на месте может исполнитель — в наблюдаемых чужих задачах
              галочки нет: она обещала бы действие, которого сервер не даст. */}
          {view === 'assigned' && (
            <button type="button" title="Закрыть задачу"
              disabled={done.isPending}
              onClick={() => done.mutate(t.id)}
              className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border border-border text-transparent transition-colors hover:border-primary hover:text-primary group-hover:text-muted-foreground">
              <Check className="size-3.5" />
            </button>
          )}
          <button type="button" onClick={() => onOpen(t.id)}
            className="flex min-w-0 flex-1 items-start gap-3 text-left">
            <span className="mt-0.5 shrink-0 font-mono text-xs text-muted-foreground">
              {tasksService.taskKey(t)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">{t.title}</span>
              <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                {t.project && <span className="text-primary/80">{t.project}</span>}
                {t.stage && <span>{t.stage}</span>}
                {t.assignee && <span>· {t.assignee}</span>}
                {t.object && <span>· {t.object}</span>}
                {dueText(t.due_at, t.overdue) && (
                  <span className={t.overdue ? 'text-red-600 dark:text-red-400' : ''}>
                    · {dueText(t.due_at, t.overdue)}
                  </span>
                )}
              </span>
            </span>
            {(t.priority === 'critical' || t.priority === 'high') && (
              <Badge variant="outline" className="mt-0.5 h-5 shrink-0 px-1.5 text-xs">
                {t.priority === 'critical' ? 'критично' : 'важно'}
              </Badge>
            )}
          </button>
        </div>
      ))}
    </div>
  )
}

/** Записная книжка: свои записи без сроков и чужих глаз. В пульте — последние,
 *  чтобы записанное утром было видно там же, где записывалось. */
/** Правая полоса: день человека. Отвечает на «что у меня сегодня» — взятое в
 *  день, чем просил напомнить и когда встречи. Списки те же, что на экране
 *  «Сегодня». */
function DayAside({ companyId, onOpen, width }: {
  companyId: string; onOpen: (href: string) => void; width: number
}) {
  const from = new Date(); from.setHours(0, 0, 0, 0)
  const to = new Date(); to.setHours(23, 59, 59, 999)

  const remindersQ = useQuery({
    queryKey: ['reminders', companyId, 'pending'],
    queryFn: () => workService.listReminders(companyId, { pending: true }),
    enabled: !!companyId,
    staleTime: 60 * 1000,
  })
  const eventsQ = useQuery({
    queryKey: ['events', companyId, from.toISOString().slice(0, 10)],
    queryFn: () => workService.listEvents(companyId, from.toISOString(), to.toISOString()),
    enabled: !!companyId,
    staleTime: 60 * 1000,
  })
  const reminders = remindersQ.data?.items ?? []
  const events = eventsQ.data?.events ?? []

  return (
    <aside style={{ '--day-w': `${width}px` } as React.CSSProperties}
      className="w-full shrink-0 space-y-4 overflow-y-auto border-t border-border/60 p-3 md:w-[var(--day-w)] md:border-t-0">
      <section>
        <h3 className="mb-1.5 flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Мой день
          <button type="button" onClick={() => onOpen('/docs/work?view=today')}
            className="text-xs font-normal normal-case tracking-normal text-primary hover:underline">
            весь день
          </button>
        </h3>
        <PlacedList companyId={companyId} scope="day"
          empty="День пуст. Возьмите из очереди слева — или оставьте пустым: это тоже решение." />
      </section>

      <section>
        <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <Bell className="size-3.5" />Напоминания
        </h3>
        {reminders.length === 0 ? (
          <p className="text-xs text-muted-foreground">Ничего не ждёт напоминания.</p>
        ) : (
          <ul className="space-y-1">
            {reminders.slice(0, 6).map((r) => (
              <li key={r.id} className="rounded-md border px-2 py-1.5">
                <p className="truncate text-sm text-foreground">{r.note || 'Напоминание'}</p>
                <p className="text-xs text-muted-foreground">{hhmm(r.remind_at)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-1.5 flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <span className="flex items-center gap-1.5"><CalendarDays className="size-3.5" />Встречи</span>
          <button type="button" onClick={() => onOpen('/docs/work?view=calendar')}
            className="text-xs font-normal normal-case tracking-normal text-primary hover:underline">
            календарь
          </button>
        </h3>
        {eventsQ.isLoading ? (
          <p className="text-xs text-muted-foreground">Смотрим календарь…</p>
        ) : events.length === 0 ? (
          <p className="text-xs text-muted-foreground">На сегодня встреч нет.</p>
        ) : (
          <ul className="space-y-1">
            {events.slice(0, 6).map((e) => (
              <li key={e.id} className="rounded-md border px-2 py-1.5">
                <p className="truncate text-sm text-foreground">{e.title}</p>
                <p className="text-xs text-muted-foreground">
                  {e.all_day ? 'весь день' : `${hhmm(e.starts_at)} — ${hhmm(e.ends_at)}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  )
}
