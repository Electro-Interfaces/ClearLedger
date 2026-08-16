/**
 * Оболочка приложения «Трек»: вторая вертикальная панель — пункты активного
 * раздела.
 *
 * Канон пространства: раздел живёт в левой рельсе, его пункты — во второй
 * колонке, заголовок экрана равен имени пункта. Геометрия взята у «Задач» и
 * «Пульса» — это такое же приложение Ядра, и человек, перешедший оттуда, не
 * должен заметить смены правил.
 */
import { useState } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useMaxWidth } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'

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
  '/docs/work': [
    { key: 'approvals', label: 'На мне', hint: 'что ждёт моей визы' },
    { key: 'mine', label: 'Мои документы', hint: 'где я автор или ответственный' },
    { key: 'board', label: 'Доска', hint: 'как идёт дело по процессу: где застряло и кого ждут' },
    { key: 'inbox', label: 'Приём из СЭД', hint: 'что головная компания положила нам в папку' },
  ],
  '/docs/errands': [
    { key: 'mine', label: 'Моя работа', hint: 'что делаю я и что поручил другим' },
    { key: 'board', label: 'Доска', hint: 'канбан по стадиям маршрута, карточка переносится мышью' },
    { key: 'all', label: 'Работа компании', hint: 'все поручения с отбором, поиском и выгрузкой' },
  ],
  '/docs/overview': [
    { key: 'docs', label: 'По документам', hint: 'сколько на регистрации, на визах, просрочено' },
    { key: 'errands', label: 'По поручениям', hint: 'итоги и разрезы по людям, типам и объектам' },
  ],
  '/docs/regulation': [
    { key: 'templates', label: 'Шаблоны', hint: 'заготовки документов и поручений с чек-листом' },
    { key: 'recurrences', label: 'Расписания', hint: 'что заводится само: акт сверки к 5 числу' },
    { key: 'views', label: 'Представления', hint: 'сохранённые отборы: свои и общие' },
  ],
  '/docs/setup': [
    { key: 'kinds', label: 'Виды документов', hint: 'вид несёт правило нумерации, маршрут и реквизиты' },
    { key: 'cases', label: 'Номенклатура дел', hint: 'дела, индексы и сроки хранения' },
    { key: 'labels', label: 'Метки', hint: 'свободные ярлыки поверх вида и состояния' },
    { key: 'counters', label: 'Нумераторы', hint: 'области нумерации и текущие значения' },
    { key: 'exchange', label: 'Обмен с СЭД', hint: 'папки корпоративных систем: куда кладём и откуда берём' },
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
  const views = DOCS_VIEWS[route] ?? []
  const v = params.get('view')
  return v && views.some((x) => x.key === v) ? v : (views[0]?.key ?? '')
}

export function DocsLayout() {
  const { pathname } = useLocation()
  const [, setParams] = useSearchParams()
  const narrow = useMaxWidth(1024)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === '1')

  const route = docsRouteOf(pathname)
  const views = DOCS_VIEWS[route] ?? []
  const active = useDocsView(route)

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
    return n
  }, { replace: true })

  if (views.length === 0) {
    return <div className="h-full min-h-0 overflow-y-auto"><Outlet /></div>
  }

  if (narrow) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div data-zone="Пункты раздела"
          className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-card px-2 py-1.5 scrollbar-hide">
          {views.map((v) => (
            <button key={v.key} type="button" onClick={() => open(v.key)} title={v.hint}
              aria-current={v.key === active ? 'page' : undefined}
              className={cn('min-h-10 shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs transition-colors sm:min-h-0',
                v.key === active
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-muted-foreground')}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="min-w-0 flex-1 overflow-y-auto px-3 py-3">
          <Outlet />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0">
      {collapsed ? (
        <nav data-zone="Пункты раздела" data-zone-side
          className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-card px-1 py-3">
          <button type="button" onClick={toggle} title="Развернуть меню раздела"
            aria-label="Развернуть меню раздела"
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </nav>
      ) : (
        <nav data-zone="Пункты раздела" data-zone-side
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
      <div className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  )
}

export default DocsLayout
