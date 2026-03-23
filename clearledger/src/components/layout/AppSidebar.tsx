import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from '@/components/ui/sidebar'
import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Settings } from 'lucide-react'

const items = [
  { to: '/', icon: LayoutDashboard, label: 'Рабочий стол', end: true },
  { to: '/settings', icon: Settings, label: 'Настройки' },
]

export function AppSidebar() {
  return (
    <Sidebar className="pt-[var(--header-height)] border-r-0">
      <SidebarContent className="px-2 py-4">
        <SidebarGroup>
          <SidebarMenu>
            {items.map((item) => (
              <SidebarMenuItem key={item.to}>
                <SidebarMenuButton asChild>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                        isActive
                          ? 'bg-primary/10 text-primary'
                          : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                      }`
                    }
                  >
                    <item.icon className="h-4 w-4 shrink-0" />
                    <span>{item.label}</span>
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}
