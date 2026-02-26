import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarSeparator,
} from '@/components/ui/sidebar'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  Camera,
  PenLine,
  FileText,
  Wallet,
  Activity,
  Image,
  Plug,
  Users,
  Scale,
  ShieldCheck,
  Settings,
  Inbox,
  type LucideIcon,
} from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useInboxCount } from '@/hooks/useEntries'

interface NavItem {
  title: string
  path: string
  icon: LucideIcon
}

const iconMap: Record<string, LucideIcon> = {
  FileText, Wallet, Activity, Image, Users, Scale, ShieldCheck,
}

const dashboardItem: NavItem = {
  title: 'Дашборд',
  path: '/',
  icon: LayoutDashboard,
}

const inputItems: NavItem[] = [
  { title: 'Загрузка', path: '/input/upload', icon: Upload },
  { title: 'Фото/Скан', path: '/input/photo', icon: Camera },
  { title: 'Ручной ввод', path: '/input/manual', icon: PenLine },
]

const integrationItems: NavItem[] = [
  { title: 'Коннекторы', path: '/connectors', icon: Plug },
]

function SidebarNavItem({ item }: { item: NavItem }) {
  return (
    <SidebarMenuItem>
      <NavLink to={item.path} end={item.path === '/'}>
        {({ isActive }) => (
          <SidebarMenuButton isActive={isActive} tooltip={item.title}>
            <item.icon className="size-4" />
            <span>{item.title}</span>
          </SidebarMenuButton>
        )}
      </NavLink>
    </SidebarMenuItem>
  )
}

function InboxNavItem() {
  const { data: count = 0 } = useInboxCount()
  return (
    <SidebarMenuItem>
      <NavLink to="/inbox">
        {({ isActive }) => (
          <SidebarMenuButton isActive={isActive} tooltip="Входящие">
            <Inbox className="size-4" />
            <span className="flex-1">Входящие</span>
            {count > 0 && (
              <span className="inline-flex items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-semibold leading-none text-primary-foreground min-w-[18px]">
                {count}
              </span>
            )}
          </SidebarMenuButton>
        )}
      </NavLink>
    </SidebarMenuItem>
  )
}

export function AppSidebar() {
  const { effectiveCategories } = useCompany()

  const dataItems: NavItem[] = effectiveCategories.map((cat) => ({
    title: cat.label,
    path: `/data/${cat.id}`,
    icon: iconMap[cat.icon] ?? FileText,
  }))

  return (
    <Sidebar collapsible="icon" style={{ paddingTop: 'var(--header-height)' }}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarNavItem item={dashboardItem} />
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="scroll-thin">
        <SidebarGroup>
          <SidebarMenu>
            <InboxNavItem />
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator />

        <SidebarGroup>
          <SidebarGroupLabel>Ввод</SidebarGroupLabel>
          <SidebarMenu>
            {inputItems.map((item) => (
              <SidebarNavItem key={item.path} item={item} />
            ))}
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator />

        <SidebarGroup>
          <SidebarGroupLabel>Данные</SidebarGroupLabel>
          <SidebarMenu>
            {dataItems.map((item) => (
              <SidebarNavItem key={item.path} item={item} />
            ))}
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator />

        <SidebarGroup>
          <SidebarGroupLabel>Интеграции</SidebarGroupLabel>
          <SidebarMenu>
            {integrationItems.map((item) => (
              <SidebarNavItem key={item.path} item={item} />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarNavItem item={{ title: 'Настройки', path: '/settings', icon: Settings }} />
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
