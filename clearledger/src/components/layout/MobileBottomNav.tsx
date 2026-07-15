import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  FileText,
  Building2,
  Boxes,
  Settings,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { routeAllowed } from '@/config/accessModules'

interface BottomNavItem {
  label: string
  path: string
  icon: React.ComponentType<{ className?: string }>
}

/**
 * Нижняя навигация для телефонов (<768px, md:hidden) — быстрый доступ к главным
 * разделам; полное меню — в шторке по гамбургеру. Пункты фильтруются RBAC.
 */
export function MobileBottomNav() {
  const { companyModules } = useCompany()
  const items: BottomNavItem[] = [
    { label: 'Рабочий стол', path: '/', icon: LayoutDashboard },
    { label: 'Документы', path: '/files', icon: FileText },
    { label: 'Контрагенты', path: '/contractors', icon: Building2 },
    { label: 'Объекты', path: '/objects', icon: Boxes },
    { label: 'Настройки', path: '/settings', icon: Settings },
  ].filter((i) => routeAllowed(i.path, companyModules))

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
                isActive
                  ? 'text-primary'
                  : 'text-muted-foreground hover:text-foreground',
              )
            }
          >
            <item.icon className="size-5" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
