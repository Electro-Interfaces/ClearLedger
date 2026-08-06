/**
 * Левое меню приложения «Управление» — тот же вид навигации, что у Учёта
 * (`AppSidebar`): те же пункты-ссылки, та же свёртка в иконки. Разница только в
 * составе разделов, он берётся из `config/adminNav`.
 *
 * Две группы = два уровня пространства: «Экосистема» (контейнер, суперадмину) и
 * «Организация» (пространство заказчика, по модулям роли). Раньше это были вкладки
 * поверх одной страницы — с меню разделы стали адресуемыми (`/admin/company/roles`).
 */
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarMenu,
  SidebarSeparator,
  useSidebar,
} from '@/components/ui/sidebar'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AppsNavItem, NavItem } from '@/components/layout/AppSidebar'
import { adminPath, companySections, ecosystemSections, sectionGroups } from '@/config/adminNav'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'

/** Содержимое меню без обёртки `<Sidebar>` — годится и для мобильной шторки. */
export function AdminNavContent({ collapsed = false, onNavigate }: {
  collapsed?: boolean; onNavigate?: () => void
}) {
  const { user } = useAuth()
  const { canModule } = useCompany()
  const isSuper = !!user?.is_superadmin
  const companyNav = companySections.filter((s) => canModule('admin', s.code))

  return (
    <>
      {/* «Приложения» — тот же первый пункт, что в меню Учёта: плашки пространства
          поверх текущего экрана. В шапке этого входа больше нет. */}
      <SidebarGroup className="py-0">
        <SidebarMenu>
          <AppsNavItem collapsed={collapsed} />
        </SidebarMenu>
      </SidebarGroup>
      <SidebarSeparator className="my-2" />

      {isSuper && (
        <SidebarGroup className="py-0">
          {!collapsed && (
            <p className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              Экосистема
            </p>
          )}
          <SidebarMenu>
            {ecosystemSections.map((s) => (
              <NavItem
                key={s.code}
                to={adminPath('eco', s.code)}
                icon={s.icon}
                label={s.label}
                collapsed={collapsed}
                onNavigate={onNavigate}
              />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      )}

      {isSuper && companyNav.length > 0 && <SidebarSeparator className="my-2" />}

      {/* Разделы организации идут БЛОКАМИ (`AdminSection.group`): организация, компании
          и партнёры, контрагенты, рабочее пространство, наблюдение. Двенадцать пунктов
          плоским списком не читаются, а вопросы у блоков разные — партнёр с доступом и
          контрагент в договоре это не одно и то же. */}
      {sectionGroups(companyNav).map((g, i) => (
        <SidebarGroup key={g.name || i} className="py-0">
          {!collapsed && g.name && (
            <p className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              {g.name}
            </p>
          )}
          {/* В свёрнутом меню подписей нет — блоки разделяем чертой, иначе иконки
              сливаются в одну колонну. */}
          {collapsed && i > 0 && <SidebarSeparator className="my-1" />}
          <SidebarMenu>
            {g.items.map((s) => (
              <NavItem
                key={s.code}
                to={adminPath('company', s.code)}
                icon={s.icon}
                label={s.label}
                collapsed={collapsed}
                onNavigate={onNavigate}
              />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      ))}
    </>
  )
}

export function AdminSidebar() {
  const { state, toggleSidebar } = useSidebar()
  const collapsed = state === 'collapsed'

  return (
    <Sidebar collapsible="icon" className="border-r border-border/40 pt-[var(--header-height)]">
      <SidebarContent data-zone="Разделы управления" data-zone-side className="px-1.5 py-1">
        <div className={`flex ${collapsed ? 'justify-center' : 'justify-end'} px-1 py-1.5`}>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}
            title={collapsed ? 'Развернуть' : 'Свернуть'}>
            {collapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <PanelLeftClose className="h-3.5 w-3.5" />}
          </Button>
        </div>

        <AdminNavContent collapsed={collapsed} />
      </SidebarContent>

      <SidebarFooter />
    </Sidebar>
  )
}
