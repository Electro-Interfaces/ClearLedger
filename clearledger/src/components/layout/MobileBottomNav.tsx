import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  Camera,
  Database,
  MoreHorizontal,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface BottomNavItem {
  label: string
  path: string
  icon: React.ComponentType<{ className?: string }>
}

const items: BottomNavItem[] = [
  { label: 'Дашборд', path: '/', icon: LayoutDashboard },
  { label: 'Загрузка', path: '/input/upload', icon: Upload },
  { label: 'Фото', path: '/input/photo', icon: Camera },
  { label: 'Данные', path: '/data/documents', icon: Database },
  { label: 'Ещё', path: '/settings', icon: MoreHorizontal },
]

export function MobileBottomNav() {
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
                'flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg text-[10px] font-medium transition-colors duration-200 min-w-[48px]',
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
