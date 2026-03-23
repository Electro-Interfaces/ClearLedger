import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarSeparator,
} from '@/components/ui/sidebar'
import { NavLink } from 'react-router-dom'
import { LayoutDashboard, ClipboardList, Truck, Settings, Fuel } from 'lucide-react'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Дашборд' },
]

const operationsItems = [
  { to: '/shifts', icon: ClipboardList, label: 'Сменные отчёты' },
  { to: '/receipts', icon: Truck, label: 'Поступления' },
]

const settingsItems = [
  { to: '/settings', icon: Settings, label: 'Настройки' },
]

export function AppSidebar() {
  return (
    <Sidebar>
      <SidebarHeader className="p-4">
        <NavLink to="/" className="flex items-center gap-2">
          <Fuel className="h-6 w-6 text-primary" />
          <span className="font-bold text-lg">GIG Fuel</span>
        </NavLink>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu>
            {navItems.map((item) => (
              <SidebarMenuItem key={item.to}>
                <SidebarMenuButton asChild>
                  <NavLink to={item.to} end className={({ isActive }) => isActive ? 'bg-accent' : ''}>
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator />

        <SidebarGroup>
          <div className="px-3 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
            Операции
          </div>
          <SidebarMenu>
            {operationsItems.map((item) => (
              <SidebarMenuItem key={item.to}>
                <SidebarMenuButton asChild>
                  <NavLink to={item.to} className={({ isActive }) => isActive ? 'bg-accent' : ''}>
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator />

        <SidebarGroup>
          <SidebarMenu>
            {settingsItems.map((item) => (
              <SidebarMenuItem key={item.to}>
                <SidebarMenuButton asChild>
                  <NavLink to={item.to} className={({ isActive }) => isActive ? 'bg-accent' : ''}>
                    <item.icon className="h-4 w-4" />
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
