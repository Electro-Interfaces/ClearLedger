import { useState } from 'react'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarFooter,
  SidebarSeparator,
  useSidebar,
} from '@/components/ui/sidebar'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Settings, PanelLeftClose, PanelLeftOpen,
  Upload, FileText, Radio, Database, ChevronDown,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const mainItems = [
  { to: '/', icon: LayoutDashboard, label: 'Рабочий стол', end: true },
]

const intakeItems = [
  { to: '/intake', icon: FileText, label: 'Файлы и документы' },
  { to: '/channels', icon: Radio, label: 'Каналы данных' },
  { to: '/sources', icon: Database, label: 'Источники' },
]

const settingsItems = [
  { to: '/settings', icon: Settings, label: 'Параметры' },
]

function NavItem({ to, icon: Icon, label, end, collapsed }: {
  to: string; icon: React.ComponentType<{ className?: string }>; label: string; end?: boolean; collapsed?: boolean
}) {
  return (
    <SidebarMenuItem>
      <Tooltip>
        <TooltipTrigger asChild>
          <SidebarMenuButton asChild>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                } ${collapsed ? 'justify-center px-2' : ''}`
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          </SidebarMenuButton>
        </TooltipTrigger>
        {collapsed && <TooltipContent side="right">{label}</TooltipContent>}
      </Tooltip>
    </SidebarMenuItem>
  )
}

export function AppSidebar() {
  const { state, toggleSidebar } = useSidebar()
  const collapsed = state === 'collapsed'
  const [intakeOpen, setIntakeOpen] = useState(true)

  return (
    <Sidebar collapsible="icon" className="pt-[var(--header-height)] border-r border-border/40">
      <SidebarContent className="px-1.5 py-1">
        {/* Toggle button */}
        <div className={`flex ${collapsed ? 'justify-center' : 'justify-end'} px-1 py-1.5`}>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}
            title={collapsed ? 'Развернуть' : 'Свернуть'}>
            {collapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <PanelLeftClose className="h-3.5 w-3.5" />}
          </Button>
        </div>

        {/* Main nav */}
        <SidebarGroup className="py-0">
          <SidebarMenu>
            {mainItems.map((item) => (
              <NavItem key={item.to} {...item} collapsed={collapsed} />
            ))}
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator className="my-2" />

        {/* ЗАГРУЗКА section */}
        <SidebarGroup className="py-0">
          {collapsed ? (
            <SidebarMenu>
              <NavItem to="/intake" icon={Upload} label="Загрузка" collapsed />
            </SidebarMenu>
          ) : (
            <Collapsible open={intakeOpen} onOpenChange={setIntakeOpen}>
              <CollapsibleTrigger asChild>
                <button className="flex items-center justify-between w-full px-3 py-1.5 text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-widest hover:text-muted-foreground transition-colors">
                  <span className="flex items-center gap-1.5">
                    <Upload className="h-3 w-3" />
                    Загрузка
                  </span>
                  <ChevronDown className={`h-3 w-3 transition-transform ${intakeOpen ? '' : '-rotate-90'}`} />
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <SidebarMenu>
                  {intakeItems.map((item) => (
                    <NavItem key={item.to} {...item} collapsed={collapsed} />
                  ))}
                </SidebarMenu>
              </CollapsibleContent>
            </Collapsible>
          )}
        </SidebarGroup>

        <SidebarSeparator className="my-2" />

        {/* Settings */}
        <SidebarGroup className="py-0">
          {!collapsed && (
            <p className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-widest">
              Настройки
            </p>
          )}
          <SidebarMenu>
            {settingsItems.map((item) => (
              <NavItem key={item.to} {...item} collapsed={collapsed} />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter />
    </Sidebar>
  )
}
