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
 *
 * На узком экране колонка уступает место свайп-строке — тем же приёмом, что и
 * рабочее место: боковое меню там съедает почти всю ширину телефона.
 */
import { useState } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useMaxWidth } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'

export interface PulseView { key: string; label: string; hint: string }

/** Пункты по разделам: каждый — самостоятельный вопрос, с которым приходят отдельно. */
export const PULSE_VIEWS: Record<string, PulseView[]> = {
  '/pulse': [
    { key: 'today', label: 'Экран дня', hint: 'что требует вмешательства и как идут дела' },
    { key: 'accepted', label: 'Принятое сегодня', hint: 'какие карточки уже сняты и кем' },
    // Пороги живут рядом с тем, что регулируют: увидел карточку — поправил
    // норму, не уходя в «Управление».
    { key: 'sources', label: 'Источники', hint: 'чему сегодня можно верить: когда что приходило' },
    { key: 'targets', label: 'Пороги', hint: 'с какого места считать, что пора вмешаться' },
    // Отбор картины для роли: куратору нужна не вся кухня, и решает это директор.
    { key: 'visibility', label: 'Кто что видит', hint: 'что из картины открыто куратору и другим ролям' },
    // Витрина — «Пульс», повёрнутый наружу: заказчику и владельцу нужна картина по
    // своей теме без погружения в приложения.
    { key: 'views', label: 'Витрины', hint: 'что показываем заказчику, владельцу, куратору со стороны' },
    { key: 'showcase', label: 'Моя витрина', hint: 'картина, собранная для вас' },
  ],
  // «Бизнес» разложен ПО ПРИЛОЖЕНИЯМ, а не по самодельным сводкам. Но пункт —
  // не всегда чужая витрина: там, где у руководителя ДРУГИЕ вопросы, чем у
  // продукта, стоит свой разрез («Продажи», «Проекты», «Эксплуатация»,
  // «Обращения», «Где болит»), а витрина открывается ссылкой внутри экрана.
  // Правило прежнее: цифры берутся из тех же таблиц и тех же определений —
  // «Пульс» переиспользует смысл, а не заводит второй набор метрик.
  '/pulse/business': [
    { key: 'sales', label: 'Продажи', hint: 'обзор сети из приложения «Продажи»' },
    { key: 'projects', label: 'Проекты', hint: 'портфель стройки из «Проектов»' },
    { key: 'ops', label: 'Эксплуатация', hint: 'состояние сети и баланс из «Эксплуатации»' },
    { key: 'support', label: 'Поддержка', hint: 'заявки и SLA из сервисного контура' },
    { key: 'tasks', label: 'Задачи', hint: 'работа компании: успеваем ли, у кого затор' },
    // «Обращения» — единственный пункт «Бизнеса» со своей витриной, а не чужой:
    // рабочее место контакт-центра отвечает оператору, а руководителю нужны
    // четыре вопроса — дозвонились, быстро ли ответили, нет ли хвостов, есть ли
    // то, что касается его лично.
    { key: 'contacts', label: 'Обращения', hint: 'разговор с потребителем: звонки, скорость, хвосты' },
    // «Где болит» — единственный экран, которого нет ни в одном приложении:
    // точка сети сразу во всех контурах (выручка, расходы, документы).
    { key: 'objects', label: 'Где болит', hint: 'точки, где сошлось несколько проблем сразу' },
    { key: 'summary', label: 'Коротко', hint: 'выжимка для куратора: цифры и вехи' },
  ],
  '/pulse/team': [
    { key: 'people', label: 'Люди', hint: 'нагрузка и присутствие' },
    { key: 'departments', label: 'Подразделения', hint: 'структура и руководители' },
    // «Доступ» — не про присутствие, а про риск: права переживают людей.
    { key: 'access', label: 'Доступ', hint: 'у кого права, кто спит, что меняли' },
    // Переписка — разрез активности, а не чтение чужих сообщений.
    { key: 'comms', label: 'Переписка', hint: 'кто пишет в чатах, чем пишут клиенты, почта' },
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
  const [, setParams] = useSearchParams()
  // Порог тот же, что у рабочего места (`WorkspaceLayout`): боковая колонка
  // оправдана только на настоящем десктопе. При 640 «Пульс» разворачивался в
  // десктопный вид на планшете и на телефоне, повёрнутом в альбом (844 px).
  const { canModule } = useCompany()
  const narrow = useMaxWidth(1024)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === '1')

  const route = Object.keys(PULSE_VIEWS).find(
    (r) => pathname === r || pathname === `${r}/`) ?? '/pulse'
  // Ключ права пункта = раздел + пункт («business.sales»), как в реестре
  // приложения. `canModule` уже умеет читать `pulse:...` из роли.
  const section = route.replace('/pulse', '').replace('/', '')
  const views = (PULSE_VIEWS[route] ?? []).filter(
    (v) => canModule('pulse', section ? `${section}.${v.key}` : v.key))
  // Тем же правилом, что и сами экраны (`usePulseView`): иначе подсветка в меню
  // и открытый пункт разъезжались бы, стоило одному из двух мест измениться.
  const active = usePulseView(route)

  const toggle = () => setCollapsed((c) => {
    localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
    return !c
  })

  const open = (key: string) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', key)
    return n
  }, { replace: true })

  // Узкий экран: боковое меню 224 px съедало почти весь телефон — на 320 px под
  // содержимое оставалось 96, и карточки экрана дня схлопывались в вертикальную
  // полоску. Пункты уходят в свайп-строку сверху, как в рабочем месте.
  if (narrow) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        {views.length > 0 && (
          <div data-zone="Пункты раздела"
            className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-card px-2 py-1.5 scrollbar-hide">
            {views.map((v) => (
              // Подсветка активного — та же, что в свайп-строке рабочего места
              // (`WorkspaceLayout`): `bg-primary/10 text-primary`. Нейтральный
              // `accent` читался как «просто наведено», и было неясно, где стоишь.
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
        )}
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
            // Канон второй колонки (`WorkspaceModeSidebar`): активный пункт —
            // `bg-primary/10 text-primary`, отступ px-3, наведение — accent/40.
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

      <div className="min-w-0 flex-1 overflow-y-auto px-4 py-4 md:px-6">
        <Outlet />
      </div>
    </div>
  )
}
