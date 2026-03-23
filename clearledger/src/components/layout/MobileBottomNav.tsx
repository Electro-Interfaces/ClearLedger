import { NavLink } from 'react-router-dom'
import { LayoutDashboard, ClipboardList, Truck, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'

const items = [
  { label: 'Дашборд', path: '/', icon: LayoutDashboard },
  { label: 'Смены', path: '/shifts', icon: ClipboardList },
  { label: 'ТТН', path: '/receipts', icon: Truck },
  { label: 'Настройки', path: '/settings', icon: Settings },
]

export function MobileBottomNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 md:hidden mobile-safe-bottom border-t bg-card"
      style={{ boxShadow: 'var(--shadow-medium)' }}>
      <div className="flex h-14 items-center justify-around">
        {items.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg text-[10px] font-medium transition-colors',
                isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
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
