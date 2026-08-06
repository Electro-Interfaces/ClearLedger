/**
 * Оболочка приложения «Задачи»: вторая вертикальная панель — пункты активного
 * раздела (ecosystem-deploy/docs/TASKS.md).
 *
 * Канон пространства: раздел живёт в левой рельсе, его пункты — во второй
 * колонке, заголовок экрана равен имени пункта. Геометрия и подсветка взяты у
 * «Пульса» (`src/pulse/PulseLayout.tsx`) — это такое же приложение Ядра, и
 * человек, перешедший оттуда, не должен заметить смены правил.
 *
 * Раздел — свой путь, пункт — `?view=`. В `CoreMode` разделы не заводятся: это
 * перечисление режимов рабочей области Учёта, «Задачи» в неё не входят.
 */
import { useState } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useMaxWidth } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'

export interface TasksView { key: string; label: string; hint: string }

/** Пункты по разделам. Каждый — свой вопрос, с которым приходят отдельно. */
export const TASKS_VIEWS: Record<string, TasksView[]> = {
  '/tasks': [
    { key: 'today', label: 'Сегодня', hint: 'что горит: просрочено и срок на носу' },
    { key: 'mine', label: 'На мне', hint: 'вся работа, которую делаю я' },
    { key: 'assigned', label: 'Я поставил', hint: 'что поручил другим и где сейчас мяч' },
    { key: 'waiting', label: 'Ждём внешних', hint: 'отдано подрядчику: мяч у внешней стороны' },
    { key: 'watching', label: 'Наблюдаю', hint: 'задачи, за которыми слежу со стороны' },
    { key: 'closed', label: 'Закрытые мои', hint: 'что уже сделано' },
  ],
  '/tasks/company': [
    { key: 'registry', label: 'Реестр', hint: 'все задачи компании с отбором и поиском' },
    { key: 'board', label: 'Доска', hint: 'стадии маршрута колонками, карточка переносится' },
    { key: 'views', label: 'Представления', hint: 'сохранённые отборы: свои и общие' },
    { key: 'objects', label: 'По объектам', hint: 'работа в разрезе объектов пространства' },
  ],
  '/tasks/setup': [
    { key: 'types', label: 'Типы и маршруты', hint: 'чем один вид работы отличается от другого' },
    { key: 'templates', label: 'Шаблоны', hint: 'заготовки задач с готовым чек-листом' },
    { key: 'recurrences', label: 'Повторяющиеся', hint: 'расписания: что ставится само' },
    { key: 'labels', label: 'Метки', hint: 'свободные ярлыки поверх типа и стадии' },
    { key: 'external', label: 'Внешние подключения', hint: 'куда можно делегировать работу' },
  ],
}

const COLLAPSE_KEY = 'cl-tasks-views-collapsed'

/** Раздел по адресу: пункты берём по нему, а не по первому совпадению префикса. */
export function tasksRouteOf(pathname: string): string {
  return Object.keys(TASKS_VIEWS).find(
    (r) => pathname === r || pathname === `${r}/`) ?? '/tasks'
}

/** Активный пункт раздела: из `?view=`, иначе первый.
 *
 *  Одна функция и для подсветки в меню, и для содержимого экрана: два независимых
 *  источника разъезжаются на первом же переходе. */
export function useTasksView(route: string): string {
  const [params] = useSearchParams()
  const views = TASKS_VIEWS[route] ?? []
  const v = params.get('view')
  return v && views.some((x) => x.key === v) ? v : (views[0]?.key ?? '')
}

export function TasksLayout() {
  const { pathname } = useLocation()
  const [, setParams] = useSearchParams()
  // Порог тот же, что у «Пульса» и рабочего места: боковая колонка оправдана
  // только на настоящем десктопе — при 640 телефон в альбоме (844 px) получал
  // десктопный вид.
  const narrow = useMaxWidth(1024)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === '1')

  const route = tasksRouteOf(pathname)
  const views = TASKS_VIEWS[route] ?? []
  const active = useTasksView(route)

  const toggle = () => setCollapsed((c) => {
    localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
    return !c
  })

  // Пункт пишется в адрес — на экран можно дать ссылку и закрепить вкладкой.
  // Открытую карточку (`?task=`) при смене пункта закрываем: иначе она висит
  // поверх другого списка и человек не понимает, откуда она.
  const open = (key: string) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', key)
    n.delete('task')
    return n
  }, { replace: true })

  // Раздел «Обзор» — один экран, второй колонки ему не нужно.
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

export default TasksLayout
