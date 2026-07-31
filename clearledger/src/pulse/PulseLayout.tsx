/**
 * Оболочка «Пульса»: вторая вертикальная панель — пункты активного раздела.
 *
 * Канон пространства (docs/SPACE.md §4): раздел живёт в левой рельсе приложения,
 * его пункты — во второй колонке, и заголовок экрана равен имени пункта. Так же
 * устроены «Продажи» и «Проекты» (`WorkspaceModeSidebar`), поэтому и здесь та же
 * геометрия: w-56, bg-card, кнопка сворачивания с запоминанием.
 *
 * Пункт пишется в `?view=` — как `?sub=` в рабочей области: на экран можно дать
 * ссылку и закрепить его вкладкой.
 */
import { useState } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface PulseView { key: string; label: string; hint: string }

/** Пункты по разделам: каждый — самостоятельный вопрос, с которым приходят отдельно. */
export const PULSE_VIEWS: Record<string, PulseView[]> = {
  '/pulse': [
    { key: 'today', label: 'Экран дня', hint: 'что требует вмешательства и как идут дела' },
    { key: 'accepted', label: 'Принятое сегодня', hint: 'какие карточки уже сняты и кем' },
  ],
  // «Бизнес» разложен ПО ПРИЛОЖЕНИЯМ, а не по самодельным сводкам (решение МАГа
  // 31.07.2026): каждый пункт показывает витрину своего продукта в том виде, в
  // котором она там живёт. Свои агрегаты дублировали бы чужую работу и разъехались
  // бы с ней через месяц — «Пульс» переиспользует, а не пересчитывает.
  '/pulse/business': [
    { key: 'sales', label: 'Продажи', hint: 'обзор сети из приложения «Продажи»' },
    { key: 'projects', label: 'Проекты', hint: 'портфель стройки из «Проектов»' },
    { key: 'ops', label: 'Эксплуатация', hint: 'состояние сети и баланс из «Эксплуатации»' },
    { key: 'support', label: 'Поддержка', hint: 'заявки и SLA из сервисного контура' },
    { key: 'summary', label: 'Коротко', hint: 'выжимка для куратора: цифры и вехи' },
  ],
  '/pulse/team': [
    { key: 'people', label: 'Люди', hint: 'нагрузка и присутствие' },
    { key: 'departments', label: 'Подразделения', hint: 'структура и руководители' },
  ],
  '/pulse/week': [
    { key: 'totals', label: 'Итоги недели', hint: 'цифры против прошлой' },
    { key: 'moves', label: 'Движения', hint: 'что сдвинулось за семь дней' },
  ],
}

const COLLAPSE_KEY = 'cl-pulse-views-collapsed'

/** Активный пункт раздела: из `?view=`, иначе первый. */
export function usePulseView(route: string): string {
  const [params] = useSearchParams()
  const views = PULSE_VIEWS[route] ?? []
  const v = params.get('view')
  return v && views.some((x) => x.key === v) ? v : (views[0]?.key ?? '')
}

export function PulseLayout() {
  const { pathname } = useLocation()
  const [params, setParams] = useSearchParams()
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === '1')

  const route = Object.keys(PULSE_VIEWS).find(
    (r) => pathname === r || pathname === `${r}/`) ?? '/pulse'
  const views = PULSE_VIEWS[route] ?? []
  const active = params.get('view') && views.some((v) => v.key === params.get('view'))
    ? params.get('view')! : views[0]?.key

  const toggle = () => setCollapsed((c) => {
    localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
    return !c
  })

  const open = (key: string) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', key)
    return n
  }, { replace: true })

  return (
    <div className="flex h-full min-h-0">
      {collapsed ? (
        <nav data-zone="Пункты раздела" data-zone-side
          className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-card px-1 py-3">
          <button onClick={toggle} title="Развернуть меню раздела"
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </nav>
      ) : (
        <nav data-zone="Пункты раздела" data-zone-side
          className="flex w-56 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border bg-card px-2.5 py-3">
          <div className="flex items-center justify-end px-1 pb-1">
            <button onClick={toggle} title="Свернуть меню"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
          {views.map((v) => (
            <button key={v.key} onClick={() => open(v.key)} title={v.hint}
              className={cn('rounded-md px-2.5 py-2 text-left text-[13px] transition-colors',
                v.key === active
                  ? 'bg-accent font-medium text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground')}>
              {v.label}
            </button>
          ))}
        </nav>
      )}

      <div className="min-w-0 flex-1 overflow-y-auto px-4 py-4 md:px-6">
        <Outlet />
      </div>
    </div>
  )
}
