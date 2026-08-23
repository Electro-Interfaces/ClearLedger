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
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import { DocsScopeBar } from '@/components/docs/DocsScopeBar'

export interface DocsView { key: string; label: string; hint: string }

/** Пункты по разделам. Каждый — свой вопрос, с которым приходят отдельно. */
export const DOCS_VIEWS: Record<string, DocsView[]> = {
  '/docs': [
    { key: 'incoming', label: 'Входящие', hint: 'что пришло: письма, претензии, требования' },
    { key: 'outgoing', label: 'Исходящие', hint: 'что отправили сами' },
    { key: 'ord', label: 'Приказы', hint: 'приказы и распоряжения по компании' },
    { key: 'internal', label: 'Внутренние', hint: 'служебные записки и прочая переписка внутри' },
    { key: 'all', label: 'Все документы', hint: 'единый реестр без разделения по потоку' },
  ],
  // Раздел «На мне» — всё, что ждёт лично меня, независимо от того, документ это
  // или поручение. Делить личное по движку бессмысленно: человек приходит с
  // вопросом «что на мне», а не «что у меня в документах».
  '/docs/work': [
    { key: 'mine-all', label: 'Моя очередь', hint: 'всё, что ждёт меня, по срочности' },
    { key: 'approvals', label: 'Визы', hint: 'документы, которые ждут моего согласования' },
    { key: 'errands', label: 'Поручения', hint: 'работа, которую делаю я и которую поручил' },
    { key: 'acquaints', label: 'Ознакомиться', hint: 'приказы и распоряжения, доведённые до меня' },
    { key: 'mine', label: 'Мои документы', hint: 'где я автор или ответственный' },
  ],
  // Раздел «Компания» — то же самое, но по всем: где стоит работа целиком.
  '/docs/company': [
    { key: 'work', label: 'Вся работа', hint: 'документы и поручения одной лентой' },
    { key: 'docs', label: 'Документы на доске', hint: 'где застряло согласование и кого ждут' },
    { key: 'errands', label: 'Поручения компании', hint: 'вся работа с отбором, поиском и выгрузкой' },
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
  const { isCompanyAdmin } = useCompany()
  const narrow = useMaxWidth(1024)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === '1')
  const mobileNavRef = useRef<HTMLElement>(null)

  const route = docsRouteOf(pathname)
  const views = (DOCS_VIEWS[route] ?? []).filter(
    (view) => view.key !== 'discipline' || isCompanyAdmin)
  const active = useDocsView(route)

  useEffect(() => {
    const requested = params.get('view')
    if (!requested || views.some((view) => view.key === requested)) return
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('view', active)
      next.delete('doc')
      next.delete('task')
      next.delete('tab')
      next.delete('page')
      return next
    }, { replace: true })
  }, [active, params, setParams, views])

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
                  v.key === active
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-muted-foreground')}>
                {v.label}
              </button>
            ))}
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
          {views.map((v) => (
            <button key={v.key} type="button" onClick={() => open(v.key)} title={v.hint}
              aria-current={v.key === active ? 'page' : undefined}
              className={cn('rounded-md px-3 py-1.5 text-left text-[13px] transition-colors',
                v.key === active
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
              {v.label}
            </button>
          ))}
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
