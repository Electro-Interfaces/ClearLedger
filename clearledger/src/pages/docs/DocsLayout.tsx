/* eslint-disable react-refresh/only-export-components */
/**
 * Оболочка приложения «Трек»: вторая вертикальная панель — пункты активного
 * раздела.
 *
 * Канон пространства: раздел живёт в левой рельсе, его пункты — во второй
 * колонке, заголовок экрана равен имени пункта. Геометрия взята у «Задач» и
 * «Пульса» — это такое же приложение Ядра, и человек, перешедший оттуда, не
 * должен заметить смены правил.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import {
  ChevronRight, GripVertical, PanelLeftClose, PanelLeftOpen, Plus,
} from 'lucide-react'
import { toast } from 'sonner'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import { DocsScopeBar } from '@/components/docs/DocsScopeBar'
import * as tasksService from '@/services/tasksService'
import * as workService from '@/services/workService'

export interface DocsView {
  key: string
  label: string
  hint: string
  /** Заголовок группы, под которым пункт стоит. Пункты одной группы идут
   *  подряд: заголовок печатается при её смене. */
  group?: string
  /** Ключ числа в сводке раздела (`useSectionCounts`). Пусто — пункт без
   *  счётчика: число, которое всегда ноль, читается как поломка. */
  badge?: string
  /** Пункт есть в адресе и в проверке вида, но в меню не рисуется: его место
   *  занимает что-то живое — например, сами подборки человека. Без такого
   *  пункта `useDocsView` считает вид неизвестным и молча откатывает его на
   *  первый, а переход выглядит как мёртвая кнопка. */
  hidden?: boolean
}

/** Пункты по разделам. Каждый — свой вопрос, с которым приходят отдельно. */
export const DOCS_VIEWS: Record<string, DocsView[]> = {
  '/docs': [
    { key: 'incoming', label: 'Входящие', hint: 'что пришло: письма, претензии, требования' },
    { key: 'outgoing', label: 'Исходящие', hint: 'что отправили сами' },
    { key: 'ord', label: 'Приказы', hint: 'приказы и распоряжения по компании' },
    { key: 'internal', label: 'Внутренние', hint: 'служебные записки и прочая переписка внутри' },
    { key: 'all', label: 'Все документы', hint: 'единый реестр без разделения по потоку' },
  ],
  // Раздел «Моё» — личное рабочее место: сверху то, что человек ведёт сам
  // (день, календарь, записи), ниже — то, что ждут от него. Делить по движку
  // бессмысленно: приходят с вопросом «что у меня», а не «что в документах».
  // Порядок пунктов и есть эта группировка, поэтому он не алфавитный.
  // Граница внутри раздела проходит не по движку, а по тому, чьё это решение.
  // Сверху — то, что человек ведёт сам: день, календарь, записи, своя раскладка.
  // Ниже — то, что принесла компания и отменить нельзя. Между ними подборки: они и
  // есть место, где чужой предмет становится разложенным по-своему.
  '/docs/work': [
    { key: 'today', label: 'Сегодня', hint: 'день целиком: что взял, что принесли, напоминания', group: 'Веду сам', badge: 'hot' },
    // Календарь и записи переехали в правую рельсу: в них заглядывают поверх
    // работы. Пункты остаются скрытыми, чтобы прежние ссылки открывали экран.
    { key: 'calendar', label: 'Календарь', hint: 'месяц и неделя: встречи и сроки вместе', hidden: true },
    { key: 'notes', label: 'Записная книжка', hint: 'что записал себе — без сроков и чужих глаз', hidden: true },
    { key: 'starred', label: 'Важное', hint: 'помеченное лично: важность своя, приоритет предмета ставит постановщик', group: 'Веду сам', badge: 'starred' },
    { key: 'deferred', label: 'Отложено', hint: 'спрятанное у себя до даты — срок компании при этом не менялся', group: 'Веду сам', badge: 'deferred' },
    { key: 'assigned', label: 'Я поставил', hint: 'что поручил другим — с меня спросят результат', group: 'Веду сам', badge: 'assigned' },
    { key: 'watching', label: 'Наблюдаю', hint: 'чужая работа, за которой слежу со стороны', group: 'Веду сам', badge: 'watching' },
    { key: 'mine-all', label: 'Моя очередь', hint: 'всё, что ждёт меня, по срочности', group: 'Ждут от меня', badge: 'queue' },
    { key: 'errands', label: 'Поручения', hint: 'работа, которую делаю я и которую поручил', group: 'Ждут от меня', badge: 'errands' },
    { key: 'approvals', label: 'Визы', hint: 'документы, которые ждут моего согласования', group: 'Ждут от меня', badge: 'approvals' },
    { key: 'acquaints', label: 'Ознакомиться', hint: 'приказы и распоряжения, доведённые до меня', group: 'Ждут от меня', badge: 'acquaints' },
    { key: 'mine', label: 'Мои документы', hint: 'где я автор или ответственный', group: 'Ждут от меня', badge: 'own' },
    { key: 'lists', label: 'Подборки', hint: 'свои подборки: завести, переименовать, удалить', hidden: true },
  ],
  // Раздел «Компания» — то же самое, но по всем: где стоит работа целиком.
  '/docs/company': [
    { key: 'work', label: 'Вся работа', hint: 'документы и поручения одной лентой' },
    { key: 'triage', label: 'Разбор', hint: 'работа без исполнителя: взять, поручить или закрыть', badge: 'triage' },
    { key: 'docs', label: 'Документы на доске', hint: 'где застряло согласование и кого ждут' },
    { key: 'errands', label: 'Поручения компании', hint: 'вся работа с отбором, поиском и выгрузкой' },
    { key: 'work-board', label: 'Доска работы', hint: 'общие колонки: документы и поручения вместе' },
    { key: 'board', label: 'Доска поручений', hint: 'канбан по стадиям маршрута' },
    { key: 'plan', label: 'Планирование', hint: 'бэклог и спринт: что берём следующим' },
    { key: 'inbox', label: 'Приём из СЭД', hint: 'что головная компания положила нам в папку' },
    { key: 'archive', label: 'Архив', hint: 'сроки хранения, запреты и акты уничтожения' },
  ],
  '/docs/overview': [
    { key: 'docs', label: 'По документам', hint: 'сколько на регистрации, на визах, просрочено' },
    { key: 'discipline', label: 'Исполнительская дисциплина', hint: 'скорость согласования и задержки по людям' },
    { key: 'errands', label: 'По поручениям', hint: 'итоги и разрезы по людям, типам и объектам' },
  ],
  '/docs/regulation': [
    { key: 'templates', label: 'Шаблоны', hint: 'заготовки документов и поручений с чек-листом' },
    { key: 'recurrences', label: 'Расписания', hint: 'что заводится само: акт сверки к 5 числу' },
    { key: 'views', label: 'Представления', hint: 'сохранённые отборы: свои и общие' },
  ],
  // Одиннадцать строк подряд не читаются списком. Группы отвечают на вопрос, с
  // которым сюда приходят: «что заводится само», «как устроена работа», «как
  // устроены документы», «что общее».
  '/docs/setup': [
    { key: 'templates', label: 'Шаблоны', hint: 'заготовки документов и поручений с чек-листом', group: 'Заводится само' },
    { key: 'recurrences', label: 'Расписания', hint: 'что заводится само: акт сверки к 5 числу', group: 'Заводится само' },
    { key: 'views', label: 'Представления', hint: 'сохранённые отборы: свои и общие', group: 'Заводится само' },
    { key: 'projects', label: 'Проекты', hint: 'контейнеры работы: свой номер задач и свои маршруты', group: 'Работа' },
    { key: 'versions', label: 'Версии', hint: 'релизы проекта: в какой версии исправлено и что в неё вошло', group: 'Работа' },
    { key: 'types', label: 'Типы и маршруты', hint: 'чем один вид работы отличается от другого', group: 'Работа' },
    { key: 'kinds', label: 'Виды документов', hint: 'вид несёт правило нумерации, маршрут и реквизиты', group: 'Документы' },
    { key: 'cases', label: 'Номенклатура дел', hint: 'дела, индексы и сроки хранения', group: 'Документы' },
    { key: 'counters', label: 'Нумераторы', hint: 'области нумерации и текущие значения', group: 'Документы' },
    { key: 'labels', label: 'Метки', hint: 'свободные ярлыки поверх вида и состояния', group: 'Общее' },
    { key: 'exchange', label: 'Обмен с СЭД', hint: 'папки корпоративных систем: куда кладём и откуда берём', group: 'Общее' },
    { key: 'substitutions', label: 'Замещения', hint: 'кто работает за человека, пока его нет', group: 'Общее' },
  ],
}

const COLLAPSE_KEY = 'cl-docs-views-collapsed'

/** Раздел по адресу: пункты берём по нему, а не по первому совпадению префикса. */
export function docsRouteOf(pathname: string): string {
  return Object.keys(DOCS_VIEWS).find(
    (r) => pathname === r || pathname === `${r}/`) ?? '/docs'
}

/** Активный пункт раздела: из `?view=`, иначе первый. Одна функция и для
 *  подсветки в меню, и для содержимого экрана: два источника разъезжаются. */
export function useDocsView(route: string): string {
  const [params] = useSearchParams()
  const { isCompanyAdmin } = useCompany()
  const views = (DOCS_VIEWS[route] ?? []).filter(
    (view) => view.key !== 'discipline' || isCompanyAdmin)
  const v = params.get('view')
  return v && views.some((x) => x.key === v) ? v : (views[0]?.key ?? '')
}

export function DocsLayout() {
  const { pathname } = useLocation()
  const [params, setParams] = useSearchParams()
  const { company, isCompanyAdmin } = useCompany()
  const qc = useQueryClient()
  const narrow = useMaxWidth(1024)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === '1')
  const mobileNavRef = useRef<HTMLElement>(null)

  const route = docsRouteOf(pathname)
  const views = (DOCS_VIEWS[route] ?? []).filter(
    (view) => (view.key !== 'discipline' || isCompanyAdmin) && !view.hidden)
  const active = useDocsView(route)

  // Сохранённые отборы общей ленты — продолжение пунктов, а не отдельный экран:
  // «Входящие за квартал» и «Разработка TF» это такие же вопросы к работе, как
  // «Доска» или «Планирование», просто заданные человеком, а не нами.
  const savedQ = useQuery({
    queryKey: ['task-views', company?.id ?? '', 'work'],
    queryFn: () => tasksService.listTaskViews(company!.id, 'work'),
    enabled: route === '/docs/company' && !!company?.id,
    staleTime: 5 * 60 * 1000,
  })
  const saved = route === '/docs/company' ? (savedQ.data?.views ?? []) : []
  const savedView = params.get('view') === 'work' ? params.get('saved') : null

  // Подборки человека — такие же пункты раздела, как «Сегодня». Держать их внутри
  // одного экрана вкладками значит спрятать личную группировку на уровень
  // глубже, чем работу компании: тогда ею не пользуются.
  const listsQ = useQuery({
    queryKey: ['personal-lists', company?.id ?? ''],
    queryFn: () => workService.myLists(company!.id),
    enabled: route === '/docs/work' && !!company?.id,
    staleTime: 60 * 1000,
  })
  const myLists = route === '/docs/work' ? (listsQ.data?.lists ?? []) : []
  const openList = params.get('view') === 'lists' ? params.get('list') : null

  // Ключи запросов те же, что у «Моей очереди», пульта и записной книжки:
  // react-query отдаёт числа из общего кэша, а не ходит на сервер второй раз.
  const личное = route === '/docs/work' && !!company?.id
  // Разбор считается и в «Компании»: число у пункта отвечает на вопрос «есть ли
  // там что-то», ради которого иначе пришлось бы открывать экран.
  const триажQ = useQuery({
    queryKey: ['tasks', company?.id ?? '', 'triage', '', '', ''],
    queryFn: () => tasksService.listTasks(company!.id, 'triage'),
    enabled: route === '/docs/company' && !!company?.id, staleTime: 60 * 1000,
  })
  const mineQ = useQuery({
    queryKey: ['work-mine', company?.id ?? ''],
    queryFn: () => workService.myWork(company!.id),
    enabled: личное, staleTime: 60 * 1000,
  })
  const assignedQ = useQuery({
    queryKey: ['tasks', company?.id ?? '', 'assigned', '', '', ''],
    queryFn: () => tasksService.listTasks(company!.id, 'assigned'),
    enabled: личное, staleTime: 60 * 1000,
  })
  const watchingQ = useQuery({
    queryKey: ['tasks', company?.id ?? '', 'watching', '', '', ''],
    queryFn: () => tasksService.listTasks(company!.id, 'watching'),
    enabled: личное, staleTime: 60 * 1000,
  })
  const notesQ = useQuery({
    queryKey: ['notes', company?.id ?? ''],
    queryFn: () => tasksService.listTasks(company!.id, 'all', {
      visibility: 'personal', sort: '-created', limit: 200,
    }),
    enabled: личное, staleTime: 60 * 1000,
  })

  // Порядок подборок человек задаёт сам. Позиции отправляются только тем, у кого
  // они изменились: перекладывание одной строки не должно означать запрос на
  // каждую подборку в списке.
  const [drag, setDrag] = useState<string | null>(null)
  const reorder = useMutation({
    mutationFn: async (order: string[]) => {
      const было = new Map(myLists.map((l, i) => [l.id, i]))
      await Promise.all(order.map((id, i) => (было.get(id) === i
        ? null
        : workService.listAction(company!.id, id, { position: i })))
        .filter(Boolean))
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['personal-lists', company?.id ?? ''] })
    },
    onError: () => toast.error('Порядок не сохранился'),
  })

  /** Переставить подборку на место другой (или на N шагов клавишами). */
  const переставить = (id: string, куда: number) => {
    const ids = myLists.map((l) => l.id)
    const из = ids.indexOf(id)
    if (из < 0 || куда < 0 || куда >= ids.length || куда === из) return
    ids.splice(куда, 0, ids.splice(из, 1)[0])
    reorder.mutate(ids)
  }

  const счёт = useMemo(() => {
    // Спрятанное человеком в числа не идёт: он его убрал с глаз, и счётчик,
    // считающий скрытое, спорит с самим смыслом отложения.
    const mine = (mineQ.data?.mine ?? []).filter((r) => !r.hidden)
    const по = (reason: string) => mine.filter((r) => r.reason === reason).length
    const c = listsQ.data?.counts
    return {
      hot: mine.filter((r) => r.bucket === 'overdue' || r.bucket === 'today').length,
      queue: mine.length,
      approvals: по('approve'),
      acquaints: по('acquaint'),
      errands: по('do') + по('unassigned'),
      own: по('own'),
      assigned: (assignedQ.data?.tasks ?? []).filter((t) => t.status === 'open').length,
      watching: (watchingQ.data?.tasks ?? []).filter((t) => t.status === 'open').length,
      notes: (notesQ.data?.tasks ?? []).filter((t) => t.status === 'open').length,
      starred: c?.starred ?? 0,
      deferred: c?.deferred ?? 0,
      // Просроченное — отдельное число: «12, из них 3 горят» это два разных
      // ответа, и одним числом они не заменяются.
      overdue: mine.filter((r) => r.overdue).length,
      triage: (триажQ.data?.tasks ?? []).length,
    } as Record<string, number>
  }, [mineQ.data, assignedQ.data, watchingQ.data, notesQ.data, listsQ.data,
      триажQ.data])

  const числоУ = (view: DocsView) => (view.badge ? счёт[view.badge] ?? 0 : 0)

  /** Открыть подборку: тот же экран подборок, но с выбранной. */
  const openMyList = (id: string | null, заводим = false) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', 'lists')
    if (id) n.set('list', id)
    else n.delete('list')
    if (заводим) n.set('new', '1')
    else n.delete('new')
    n.delete('doc')
    n.delete('task')
    return n
  }, { replace: true })

  // Отбор открывается на общей ленте: он её и описывает.
  const openSaved = (id: string, query: Record<string, string>) => setParams((p) => {
    const n = new URLSearchParams(p)
    for (const key of ['scope', 'kind', 'state', 'query', 'page', 'doc', 'task']) {
      n.delete(key)
    }
    n.set('view', 'work')
    n.set('saved', id)
    for (const [key, value] of Object.entries(query)) {
      if (value && ['scope', 'kind', 'state', 'query'].includes(key)) n.set(key, value)
    }
    return n
  }, { replace: true })

  useEffect(() => {
    const requested = params.get('view')
    // Сверяемся со ВСЕМИ пунктами раздела, включая скрытые: `views` их не
    // содержит, и вид «Подборки» считался бы неизвестным — эффект переписывал бы
    // адрес на каждом рендере, хотя вид верный.
    const known = (DOCS_VIEWS[route] ?? []).some((view) => view.key === requested)
    if (!requested || known) return
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('view', active)
      next.delete('doc')
      next.delete('task')
      next.delete('tab')
      next.delete('page')
      return next
    }, { replace: true })
  }, [active, params, route, setParams])

  useEffect(() => {
    if (!narrow) return
    const current = mobileNavRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
    current?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [active, narrow])

  const toggle = () => setCollapsed((c) => {
    localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
    return !c
  })

  // Пункт пишется в адрес — на экран можно дать ссылку. Открытую карточку
  // (`?doc=`) при смене пункта закрываем: иначе она висит поверх другого списка.
  const open = (key: string) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', key)
    n.delete('doc')
    n.delete('task')
    n.delete('tab')
    n.delete('page')
    n.delete('list')
    return n
  }, { replace: true })

  if (views.length === 0) {
    return <div className="h-full min-h-0 overflow-y-auto"><Outlet /></div>
  }

  if (narrow) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="relative shrink-0 border-b border-border bg-card">
          <nav ref={mobileNavRef} data-zone="Пункты раздела"
            aria-label="Пункты раздела Трека"
            className="flex gap-1 overflow-x-auto px-2 py-1.5 pr-12 scrollbar-hide">
            {views.map((v) => (
              <button key={v.key} type="button" onClick={() => open(v.key)} title={v.hint}
                aria-current={v.key === active ? 'page' : undefined}
                className={cn('min-h-11 shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  v.key === active && !savedView
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground')}>
                {v.label}
              </button>
            ))}
            {saved.map((v) => (
              <button key={v.id} type="button"
                onClick={() => openSaved(v.id, v.query as Record<string, string>)}
                aria-current={savedView === v.id ? 'page' : undefined}
                className={cn('min-h-11 shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-xs transition-colors',
                  savedView === v.id
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground/80')}>
                {v.name}
              </button>
            ))}
            {myLists.map((l) => (
              <button key={l.id} type="button" onClick={() => openMyList(l.id)}
                aria-current={openList === l.id ? 'page' : undefined}
                className={cn('min-h-11 shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-xs transition-colors',
                  openList === l.id
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground/80')}>
                {l.name}{l.count > 0 && <span className="ml-1 tabular-nums opacity-70">{l.count}</span>}
              </button>
            ))}
            {route === '/docs/work' && (
              <button type="button" onClick={() => openMyList(null)}
                aria-current={active === 'lists' && !openList ? 'page' : undefined}
                className="min-h-11 shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-xs text-muted-foreground/80">
                Подборки
              </button>
            )}
          </nav>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex w-12 items-center justify-end bg-gradient-to-l from-card via-card/90 to-transparent pr-1">
            <button type="button" aria-label="Показать следующие пункты раздела"
              className="pointer-events-auto flex size-10 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => mobileNavRef.current?.scrollBy({ left: 180, behavior: 'smooth' })}>
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
        <DocsScopeBar />
        <div className="min-w-0 flex-1 overflow-y-auto px-3 py-3">
          <Outlet />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0">
      {collapsed ? (
        <nav data-zone="Пункты раздела" data-zone-side aria-label="Пункты раздела Трека"
          className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-card px-1 py-3">
          <button type="button" onClick={toggle} title="Развернуть меню раздела"
            aria-label="Развернуть меню раздела"
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </nav>
      ) : (
        <nav data-zone="Пункты раздела" data-zone-side aria-label="Пункты раздела Трека"
          className="flex w-56 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border bg-card px-2.5 py-3">
          <div className="flex items-center justify-end px-1 pb-1">
            <button type="button" onClick={toggle} title="Свернуть меню"
              aria-label="Свернуть меню раздела"
              className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
          {views.map((v, i) => (
            <div key={v.key}>
              {v.group && v.group !== views[i - 1]?.group && (
                <div className={cn('px-3 pb-1 text-xs uppercase tracking-wide text-muted-foreground/70',
                  i > 0 && 'mt-3')}>
                  {v.group}
                </div>
              )}
              {/* Пункт сдвинут вправо от заголовка группы: заголовок называет
                  раздел, пункты принадлежат ему, и одинаковый левый край читался
                  бы как плоский список без групп. */}
              <button type="button" onClick={() => open(v.key)} title={v.hint}
                aria-current={v.key === active ? 'page' : undefined}
                className={cn('flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-3 text-left text-sm transition-colors',
                  v.key === active && !savedView && !openList
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
                <span className="flex-1 truncate">{v.label}</span>
                {(v.badge === 'queue' || v.badge === 'hot') && счёт.overdue > 0 && (
                  <span className="shrink-0 text-xs tabular-nums text-red-600 dark:text-red-400"
                    title={`Просрочено: ${счёт.overdue}`}>
                    {счёт.overdue}
                  </span>
                )}
                {числоУ(v) > 0 && (
                  <span className="shrink-0 text-xs tabular-nums opacity-70">{числоУ(v)}</span>
                )}
              </button>
            </div>
          ))}
          {route === '/docs/work' && (
            <>
              {/* Черта отделяет данное системой от собранного человеком: выше —
                  разрезы, которые он не заводил, ниже — его подборки. Заголовок
                  «Подборки» над подборками повторял бы очевидное, поэтому он
                  здесь работает: открывает экран подборок, а плюс заводит новую. */}
              <div className="mt-3 flex items-center gap-1 border-t border-border pt-2">
                <button type="button" onClick={() => openMyList(null)}
                  aria-current={active === 'lists' && !openList ? 'page' : undefined}
                  title="Все подборки: завести, переименовать, удалить"
                  className={cn('flex-1 rounded-md px-3 py-1 text-left text-xs uppercase tracking-wide transition-colors',
                    active === 'lists' && !openList
                      ? 'font-medium text-primary'
                      : 'text-muted-foreground/70 hover:text-foreground')}>
                  Подборки
                </button>
                <button type="button" onClick={() => openMyList(null, true)}
                  aria-label="Завести подборку" title="Завести подборку"
                  className="rounded-md p-1 text-muted-foreground/70 transition-colors hover:bg-accent/40 hover:text-foreground">
                  <Plus className="h-4 w-4" />
                </button>
              </div>
              {myLists.map((l, i) => (
                <button key={l.id} type="button" onClick={() => openMyList(l.id)}
                  draggable
                  onDragStart={() => setDrag(l.id)}
                  onDragOver={(e) => { if (drag && drag !== l.id) e.preventDefault() }}
                  onDrop={(e) => {
                    e.preventDefault()
                    if (drag) переставить(drag, i)
                    setDrag(null)
                  }}
                  onDragEnd={() => setDrag(null)}
                  // Клавиатура умеет то же самое: перетаскивание мышью не должно
                  // быть единственным способом задать порядок.
                  onKeyDown={(e) => {
                    if (!e.altKey) return
                    if (e.key === 'ArrowUp') { e.preventDefault(); переставить(l.id, i - 1) }
                    if (e.key === 'ArrowDown') { e.preventDefault(); переставить(l.id, i + 1) }
                  }}
                  aria-current={openList === l.id ? 'page' : undefined}
                  title={l.stale_days !== null && l.stale_days > 13
                    ? `Не открывали ${l.stale_days} дн. · Alt+↑↓ или перетаскиванием — порядок`
                    : 'Своя подборка: видите только вы. Alt+↑↓ или перетаскиванием — порядок'}
                  className={cn('group relative flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-3 text-left text-sm transition-colors',
                    drag === l.id && 'opacity-50',
                    openList === l.id
                      ? 'bg-primary/10 font-medium text-primary'
                      : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
                  {/* Видна всегда: порядок подборок меняют мышью, и знать об
                      этом надо до того, как случайно навёл курсор. */}
                  <GripVertical
                    className="absolute left-1.5 h-3.5 w-3.5 opacity-30 transition-opacity group-hover:opacity-70"
                    aria-hidden />
                  <span className="flex-1 truncate">{l.name}</span>
                  {l.stale_days !== null && l.stale_days > 13 && (
                    <span className="shrink-0 text-amber-600 dark:text-amber-400" aria-hidden>·</span>
                  )}
                  {l.count > 0 && (
                    <span className="shrink-0 text-xs tabular-nums opacity-70">{l.count}</span>
                  )}
                </button>
              ))}
              {myLists.length === 0 && (
                <button type="button" onClick={() => openMyList(null, true)}
                  className="rounded-md py-1.5 pl-7 pr-3 text-left text-sm text-muted-foreground/80 transition-colors hover:bg-accent/40 hover:text-foreground">
                  Завести подборку
                </button>
              )}
            </>
          )}
          {saved.length > 0 && (
            <>
              <div className="mt-3 px-3 pb-1 text-xs uppercase tracking-wide text-muted-foreground/70">
                Мои отборы
              </div>
              {saved.map((v) => (
                <button key={v.id} type="button"
                  onClick={() => openSaved(v.id, v.query as Record<string, string>)}
                  aria-current={savedView === v.id ? 'page' : undefined}
                  className={cn('truncate rounded-md py-1.5 pl-7 pr-3 text-left text-sm transition-colors',
                    savedView === v.id
                      ? 'bg-primary/10 font-medium text-primary'
                      : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
                  {v.name}
                </button>
              ))}
            </>
          )}
        </nav>
      )}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <DocsScopeBar />
        <div className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </div>
  )
}

export default DocsLayout
