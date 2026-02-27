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
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  PackageOpen,
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
  LogOut,
  BarChart3,
  BookOpen,
  Download,
  GitCompare,
  type LucideIcon,
} from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import { useInboxCount } from '@/hooks/useEntries'
import { useReferenceStats } from '@/hooks/useReferences'

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
  { title: 'Приём', path: '/input', icon: PackageOpen },
]

const systemItems: NavItem[] = [
  { title: 'Коннекторы', path: '/connectors', icon: Plug },
]

function SidebarNavItem({ item }: { item: NavItem }) {
  return (
    <SidebarMenuItem>
      <NavLink to={item.path} end={item.path === '/' || item.path === '/data'}>
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

function ReferenceNavItem() {
  const { data: stats } = useReferenceStats()
  const total = stats
    ? stats.counterparties + stats.organizations + stats.nomenclature + stats.contracts + (stats.warehouses || 0) + (stats.bankAccounts || 0)
    : 0
  return (
    <SidebarMenuItem>
      <NavLink to="/references">
        {({ isActive }) => (
          <SidebarMenuButton isActive={isActive} tooltip="Справочники">
            <BookOpen className="size-4" />
            <span className="flex-1">Справочники</span>
            {total > 0 && (
              <span className="inline-flex items-center justify-center rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-muted-foreground min-w-[18px]">
                {total}
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
  const { isApiMode, user, logout } = useAuth()
  const navigate = useNavigate()

  const dataItems: NavItem[] = [
    { title: 'Все данные', path: '/data', icon: FileText },
    ...effectiveCategories.map((cat) => ({
      title: cat.label,
      path: `/data/${cat.id}`,
      icon: iconMap[cat.icon] ?? FileText,
    })),
  ]

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
          <SidebarMenu>
            <ReferenceNavItem />
            <SidebarNavItem item={{ title: 'Сверка', path: '/reconciliation', icon: GitCompare }} />
            <SidebarNavItem item={{ title: 'Экспорт', path: '/export', icon: Download }} />
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator />

        <SidebarGroup>
          <SidebarGroupLabel>Аналитика</SidebarGroupLabel>
          <SidebarMenu>
            <SidebarNavItem item={{ title: 'Отчёты', path: '/reports', icon: BarChart3 }} />
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator />

        <SidebarGroup>
          <SidebarGroupLabel>Система</SidebarGroupLabel>
          <SidebarMenu>
            {systemItems.map((item) => (
              <SidebarNavItem key={item.path} item={item} />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarNavItem item={{ title: 'Настройки', path: '/settings', icon: Settings }} />
          {isApiMode && user && (
            <SidebarMenuItem>
              <SidebarMenuButton
                tooltip="Выйти"
                onClick={() => { logout(); navigate('/login') }}
              >
                <LogOut className="size-4" />
                <span>{user.name}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
