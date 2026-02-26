import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  Inbox,
  Database,
  MoreHorizontal,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useInboxCount } from '@/hooks/useEntries'

interface BottomNavItem {
  label: string
  path: string
  icon: React.ComponentType<{ className?: string }>
  badge?: number
}

export function MobileBottomNav() {
  const { data: inboxCount = 0 } = useInboxCount()

  const items: BottomNavItem[] = [
    { label: 'Дашборд', path: '/', icon: LayoutDashboard },
    { label: 'Приём', path: '/input', icon: Upload },
    { label: 'Входящие', path: '/inbox', icon: Inbox, badge: inboxCount },
    { label: 'Данные', path: '/data/documents', icon: Database },
    { label: 'Ещё', path: '/settings', icon: MoreHorizontal },
  ]

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-50 md:hidden mobile-safe-bottom"
      style={{
        background: 'hsl(215 28% 8%)',
        borderTop: '1px solid hsl(217 32% 20% / 0.5)',
        boxShadow: '0 -4px 16px rgba(0, 0, 0, 0.35)',
      }}
    >
      <div className="flex h-14 items-center justify-around">
        {items.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'relative flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg text-[10px] font-medium transition-colors duration-200 min-w-[48px]',
                isActive
                  ? 'text-primary'
                  : 'text-muted-foreground hover:text-foreground',
              )
            }
          >
            <div className="relative">
              <item.icon className="size-5" />
              {item.badge !== undefined && item.badge > 0 && (
                <span className="absolute -top-1.5 -right-2 min-w-[16px] h-4 px-1 rounded-full bg-primary text-[10px] font-bold text-primary-foreground flex items-center justify-center">
                  {item.badge > 99 ? '99+' : item.badge}
                </span>
              )}
            </div>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
