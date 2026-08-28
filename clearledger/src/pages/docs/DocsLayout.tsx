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
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
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
  /** Какое число показать справа. Числа личного приходят одним запросом
   *  вместе с подборками — считать их поштучно значит пять запросов на открытие. */
  badge?: 'day' | 'starred' | 'deferred'
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
    { key: 'today', label: 'Сегодня', hint: 'день целиком: что взял, что принесли, напоминания', group: 'Веду сам', badge: 'day' },
    { key: 'calendar', label: 'Календарь', hint: 'месяц и неделя: встречи и сроки вместе', group: 'Веду сам' },
    { key: 'notes', label: 'Записная книжка', hint: 'что записал себе — без сроков и чужих глаз', group: 'Веду сам' },
    { key: 'starred', label: 'Важное', hint: 'помеченное лично: важность своя, приоритет предмета ставит постановщик', group: 'Веду сам', badge: 'starred' },
    { key: 'deferred', label: 'Отложено', hint: 'спрятанное у себя до даты — срок компании при этом не менялся', group: 'Веду сам', badge: 'deferred' },
    { key: 'assigned', label: 'Я поставил', hint: 'что поручил другим — с меня спросят результат', group: 'Веду сам' },
    { key: 'watching', label: 'Наблюдаю', hint: 'чужая работа, за которой слежу со стороны', group: 'Веду сам' },
    { key: 'mine-all', label: 'Моя очередь', hint: 'всё, что ждёт меня, по срочности', group: 'Ждут от меня' },
    { key: 'errands', label: 'Поручения', hint: 'работа, которую делаю я и которую поручил', group: 'Ждут от меня' },
    { key: 'approvals', label: 'Визы', hint: 'документы, которые ждут моего согласования', group: 'Ждут от меня' },
    { key: 'acquaints', label: 'Ознакомиться', hint: 'приказы и распоряжения, доведённые до меня', group: 'Ждут от меня' },
    { key: 'mine', label: 'Мои документы', hint: 'где я автор или ответственный', group: 'Ждут от меня' },
    { key: 'lists', label: 'Подборки', hint: 'свои подборки: завести, переименовать, удалить', hidden: true },
  ],
  // Раздел «Компания» — то же самое, но по всем: где стоит работа целиком.
  '/docs/company': [
    { key: 'work', label: 'Вся работа', hint: 'документы и поручения одной лентой' },
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
  '/docs/setup': [
    { key: 'projects', label: 'Проекты', hint: 'контейнеры работы: свой номер задач и свои маршруты' },
    { key: 'versions', label: 'Версии', hint: 'релизы проекта: в какой версии исправлено и что в неё вошло' },
    { key: 'types', label: 'Типы и маршруты', hint: 'чем один вид работы отличается от другого' },
    { key: 'kinds', label: 'Виды документов', hint: 'вид несёт правило нумерации, маршрут и реквизиты' },
    { key: 'cases', label: 'Номенклатура дел', hint: 'дела, индексы и сроки хранения' },
    { key: 'labels', label: 'Метки', hint: 'свободные ярлыки поверх вида и состояния' },
    { key: 'counters', label: 'Нумераторы', hint: 'области нумерации и текущие значения' },
    { key: 'exchange', label: 'Обмен с СЭД', hint: 'папки корпоративных систем: куда кладём и откуда берём' },
    { key: 'substitutions', label: 'Замещения', hint: 'кто работает за человека, пока его нет' },
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
  const counts = listsQ.data?.counts
  const openList = params.get('view') === 'lists' ? params.get('list') : null
  const числоУ = (view: DocsView) => (view.badge && counts
    ? counts[view.badge] : 0)

  /** Открыть подборку: тот же экран подборок, но с выбранной. */
  const openMyList = (id: string | null) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', 'lists')
    if (id) n.set('list', id)
    else n.delete('list')
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
              <button type="button" onClick={() => open(v.key)} title={v.hint}
                aria-current={v.key === active ? 'page' : undefined}
                className={cn('flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors',
                  v.key === active && !savedView && !openList
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
                <span className="flex-1 truncate">{v.label}</span>
                {числоУ(v) > 0 && (
                  <span className="shrink-0 text-xs tabular-nums opacity-70">{числоУ(v)}</span>
                )}
              </button>
            </div>
          ))}
          {route === '/docs/work' && (
            <>
              <div className="mt-3 px-3 pb-1 text-xs uppercase tracking-wide text-muted-foreground/70">
                Подборки
              </div>
              {myLists.map((l) => (
                <button key={l.id} type="button" onClick={() => openMyList(l.id)}
                  aria-current={openList === l.id ? 'page' : undefined}
                  title={l.stale_days !== null && l.stale_days > 13
                    ? `Не открывали ${l.stale_days} дн.`
                    : 'Своя подборка: видите только вы'}
                  className={cn('flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors',
                    openList === l.id
                      ? 'bg-primary/10 font-medium text-primary'
                      : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
                  <span className="flex-1 truncate">{l.name}</span>
                  {l.stale_days !== null && l.stale_days > 13 && (
                    <span className="shrink-0 text-amber-600 dark:text-amber-400" aria-hidden>·</span>
                  )}
                  {l.count > 0 && (
                    <span className="shrink-0 text-xs tabular-nums opacity-70">{l.count}</span>
                  )}
                </button>
              ))}
              {/* Один вход, а не три: экран подборок и есть место, где их
                  заводят, переименовывают и удаляют. */}
              <button type="button" onClick={() => openMyList(null)}
                aria-current={active === 'lists' && !openList ? 'page' : undefined}
                className={cn('rounded-md px-3 py-1.5 text-left text-sm transition-colors',
                  active === 'lists' && !openList
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground/80 hover:bg-accent/40 hover:text-foreground')}>
                {myLists.length ? 'Все подборки' : 'Завести подборку'}
              </button>
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
                  className={cn('truncate rounded-md px-3 py-1.5 text-left text-sm transition-colors',
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
