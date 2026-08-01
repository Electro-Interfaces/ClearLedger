import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  FileText,
  Building2,
  Boxes,
  Settings,
  Activity,
  TrendingUp,
  Users,
  CalendarDays,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { routeAllowed } from '@/config/accessModules'
import { pathAllowed, homePath, SPACE_PRODUCTS } from '@/config/spaceProducts'
import { productModuleAllowed } from '@/config/productAccess'
import { useWorkspaceSections } from '@/components/workspace/workspaceSections'

interface BottomNavItem {
  label: string
  path: string
  icon: React.ComponentType<{ className?: string }>
}

/** Разделы «Пульса» — у него собственные маршруты, а не режимы рабочей области. */
const PULSE_ITEMS: BottomNavItem[] = [
  { label: 'Экран дня', path: '/pulse', icon: Activity },
  { label: 'Бизнес', path: '/pulse/business', icon: TrendingUp },
  { label: 'Команда', path: '/pulse/team', icon: Users },
  { label: 'Неделя', path: '/pulse/week', icon: CalendarDays },
]

/**
 * Нижняя навигация для телефонов (<768px, md:hidden).
 *
 * Показывает разделы ТЕКУЩЕГО приложения — то, чем работают внутри продукта. Общие
 * страницы пространства (объекты, документы, контрагенты, настройки) сюда больше не
 * попадают: они живут в меню под гамбургером, и держать их в двух местах сразу значило
 * тратить самую доступную полосу экрана на повтор (решение МАГа 01.08.2026).
 *
 * Вне продукта — на рабочем столе, в админке, чатах — приложения нет, и полоса
 * возвращается к общим страницам: иначе она осталась бы пустой.
 */
export function MobileBottomNav() {
  const { company, companyModules, canApp, canModule } = useCompany()
  const { pathname } = useLocation()
  // Разделы рабочей области: без фильтра lockedModes (он живёт в контексте самой
  // области), поэтому продукт отбирает свои режимы сам — по списку из реестра.
  const sections = useWorkspaceSections()

  // Продукт определяем СТРОГО по его корню. `productForPath` для общих страниц Ядра
  // («Объекты», «Документы») отдаёт первый продукт по фолбэку — и полоса показывала
  // разделы «Проектов» там, где никаких «Проектов» нет.
  const product = SPACE_PRODUCTS.find(
    (p) => pathname === p.route || pathname.startsWith(`${p.route}/`)) ?? null
  /** Общие страницы пространства — запасной набор там, где приложения нет. */
  const spaceItems = [
    // У разрезанного профиля Учёта как места нет — его роль играет рабочий стол
    // пространства, откуда открываются продукты.
    { label: 'Рабочий стол', path: homePath(company.profileId), icon: LayoutDashboard },
    { label: 'Документы', path: '/files', icon: FileText },
    { label: 'Контрагенты', path: '/contractors', icon: Building2 },
    { label: 'Объекты', path: '/objects', icon: Boxes },
    { label: 'Настройки', path: '/settings', icon: Settings },
  ].filter((i) => pathAllowed(i.path, company.profileId, canApp,
    (p) => routeAllowed(p, companyModules),
    (app, code) => productModuleAllowed(app, code, canModule, company.profileId)))

  let items: BottomNavItem[]

  if (pathname === '/pulse' || pathname.startsWith('/pulse/')) {
    items = PULSE_ITEMS
  } else if (product) {
    // Раздел рабочей области живёт в URL (`?mode=`), поэтому полосе хватает ссылки —
    // контекст области ей не нужен.
    items = sections
      .filter((s) => product.modes.includes(s.mode))
      .map((s) => ({ label: s.label, path: `${product.route}?mode=${s.mode}`, icon: s.icon }))
    // У продукта может не оказаться ни одного подключённого раздела (профиль fuel,
    // «Проекты»): пустая полоса скрывалась целиком, и человек оставался в приложении
    // вовсе без нижней навигации. Тогда возвращаем общие страницы.
    if (items.length === 0) items = spaceItems
  } else {
    items = spaceItems
  }

  // Больше пяти не помещается: подписи начинают обрезаться до неразличимых огрызков.
  // Остальные разделы продукта достаются из меню под гамбургером.
  items = items.slice(0, 5)
  if (items.length === 0) return null

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-50 md:hidden mobile-safe-bottom border-t bg-card"
      style={{ boxShadow: 'var(--shadow-medium)' }}
    >
      <div className="flex h-14 items-center justify-around">
        {items.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'relative flex flex-col items-center gap-0.5 px-2 py-1.5 rounded-lg text-[10px] font-medium transition-colors duration-200 min-w-[48px]',
                // Раздел продукта отличается от собрата только строкой запроса, а её
                // NavLink в isActive не смотрит — сверяем сами.
                (isActive && !item.path.includes('?')) || isCurrent(item.path, pathname)
                  ? 'text-primary'
                  : 'text-muted-foreground hover:text-foreground',
              )
            }
          >
            <item.icon className="size-5" />
            <span className="max-w-[64px] truncate">{item.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

/** Активен ли пункт с `?mode=` — сравниваем путь и режим с текущим адресом. */
function isCurrent(to: string, pathname: string): boolean {
  const [path, query] = to.split('?')
  if (path !== pathname || !query) return false
  const mode = new URLSearchParams(query).get('mode')
  return !!mode && new URLSearchParams(window.location.search).get('mode') === mode
}
