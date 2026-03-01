import { useState, useCallback } from 'react'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarSeparator,
} from '@/components/ui/sidebar'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  PackageOpen,
  FileText,
  Settings,
  Inbox,
  Upload,
  Radio,
  ShieldCheck,
  LogOut,
  BarChart3,
  BookOpen,
  Download,
  GitCompare,
  Building2,
  Database,
  Bot,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useInboxCount } from '@/hooks/useEntries'
import { useReferenceStats } from '@/hooks/useReferences'
import { useNormalizationSummary } from '@/hooks/useNormalization'

interface NavItem {
  title: string
  path: string
  icon: LucideIcon
}

// ---- Persist collapsed state ----

const STORAGE_KEY = 'clearledger-sidebar-collapsed'

function loadCollapsed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return {}
}

function saveCollapsed(state: Record<string, boolean>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch { /* ignore */ }
}

// ---- Nav items ----

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

function NormalizationNavItem() {
  const { data: summary } = useNormalizationSummary()
  const pending = summary?.pendingCount ?? 0
  return (
    <SidebarMenuItem>
      <NavLink to="/normalization">
        {({ isActive }) => (
          <SidebarMenuButton isActive={isActive} tooltip="Нормализация">
            <ShieldCheck className="size-4" />
            <span className="flex-1">Нормализация</span>
            {pending > 0 && (
              <span className="inline-flex items-center justify-center rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-amber-700 min-w-[18px]">
                {pending}
              </span>
            )}
          </SidebarMenuButton>
        )}
      </NavLink>
    </SidebarMenuItem>
  )
}

// ---- Collapsible group (TradeFrame style) ----

interface CollapsibleGroupProps {
  id: string
  label: string
  icon: LucideIcon
  defaultOpen?: boolean
  collapsed: Record<string, boolean>
  onToggle: (id: string, open: boolean) => void
  children: React.ReactNode
}

function CollapsibleSidebarGroup({ id, label, icon: Icon, defaultOpen = true, collapsed, onToggle, children }: CollapsibleGroupProps) {
  const isOpen = collapsed[id] === undefined ? defaultOpen : !collapsed[id]

  return (
    <Collapsible open={isOpen} onOpenChange={(open) => onToggle(id, open)}>
      <SidebarGroup className="py-0">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="w-full text-sidebar-foreground text-sm font-semibold tracking-wider hover:bg-sidebar-accent active:bg-sidebar-accent transition-all duration-200 ease-in-out flex items-center gap-3 uppercase px-3 py-3 rounded-md cursor-pointer select-none"
          >
            <Icon className="size-5 shrink-0 opacity-70" />
            <span className="flex-1 text-left">{label}</span>
            <ChevronRight
              className={`size-4 shrink-0 opacity-50 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`}
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <SidebarMenu>
            {children}
          </SidebarMenu>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  )
}

// ---- Main sidebar ----

export function AppSidebar() {
  const { isApiMode, user, logout } = useAuth()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(loadCollapsed)

  const handleToggle = useCallback((id: string, open: boolean) => {
    setCollapsed((prev) => {
      const next = { ...prev, [id]: !open }
      saveCollapsed(next)
      return next
    })
  }, [])

  return (
    <Sidebar collapsible="icon" style={{ paddingTop: 'var(--header-height)' }}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarNavItem item={{ title: 'Дашборд', path: '/', icon: LayoutDashboard }} />
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="scroll-thin px-2">
        {/* ── Блок 1: Поступление ── */}
        <CollapsibleSidebarGroup id="intake" label="Поступление" icon={PackageOpen} collapsed={collapsed} onToggle={handleToggle}>
          <InboxNavItem />
          <SidebarNavItem item={{ title: 'Загрузить', path: '/input', icon: Upload }} />
          <SidebarNavItem item={{ title: 'Каналы', path: '/channels', icon: Radio }} />
          <NormalizationNavItem />
        </CollapsibleSidebarGroup>

        <SidebarSeparator className="mx-0" />

        {/* ── Блок 2: Документы ── */}
        <CollapsibleSidebarGroup id="documents" label="Документы" icon={FileText} collapsed={collapsed} onToggle={handleToggle}>
          <SidebarNavItem item={{ title: 'Все данные', path: '/data', icon: FileText }} />
          <SidebarNavItem item={{ title: 'Отчёты', path: '/reports', icon: BarChart3 }} />
          <SidebarNavItem item={{ title: 'Экспорт', path: '/export', icon: Download }} />
        </CollapsibleSidebarGroup>

        <SidebarSeparator className="mx-0" />

        {/* ── Блок 3: База (эталонные данные, 1С) ── */}
        <CollapsibleSidebarGroup id="base" label="База" icon={Database} collapsed={collapsed} onToggle={handleToggle}>
          <ReferenceNavItem />
          <SidebarNavItem item={{ title: 'Сверка', path: '/reconciliation', icon: GitCompare }} />
        </CollapsibleSidebarGroup>

        <SidebarSeparator className="mx-0" />

        {/* ── Блок 4: Партнёр ── */}
        <CollapsibleSidebarGroup id="partner" label="Партнёр" icon={Bot} defaultOpen={false} collapsed={collapsed} onToggle={handleToggle}>
          <SidebarNavItem item={{ title: 'AI Аудитор', path: '/partner/auditor', icon: Bot }} />
        </CollapsibleSidebarGroup>

        <SidebarSeparator className="mx-0" />

        {/* ── Блок 5: Настройки ── */}
        <CollapsibleSidebarGroup id="settings" label="Настройки" icon={Settings} defaultOpen={false} collapsed={collapsed} onToggle={handleToggle}>
          <SidebarNavItem item={{ title: 'Компании', path: '/settings/companies', icon: Building2 }} />
          <SidebarNavItem item={{ title: 'Параметры', path: '/settings', icon: Settings }} />
        </CollapsibleSidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        {isApiMode && user && (
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                tooltip="Выйти"
                onClick={() => { logout(); navigate('/login') }}
              >
                <LogOut className="size-4" />
                <span>{user.name}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        )}
      </SidebarFooter>
    </Sidebar>
  )
}
