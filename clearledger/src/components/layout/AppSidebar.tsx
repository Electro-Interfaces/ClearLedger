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
import { NavLink, useLocation } from 'react-router-dom'
import {
  PanelLeftClose, PanelLeftOpen, ChevronDown, Database, Layers,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useCompany } from '@/contexts/CompanyContext'
import { mainNavItems, dataItems, oneCItems, settingsItems } from '@/config/navigation'
import { routeAllowed } from '@/config/accessModules'
import {
  SPACE_LINKS, isCarvedProfile, productForPath, productNav, spaceNav,
} from '@/config/spaceProducts'
import { productModuleAllowed, productHasModule } from '@/config/productAccess'
import { useWorkspaceSections } from '@/components/workspace/workspaceSections'

/** Пункт левого меню. Общий для Учёта и Управления — вид навигации один на приложения.
 *  `active` — переопределить подсветку: у разделов рабочей области адрес один и тот же,
 *  различает их параметр `?mode=`, которого NavLink не видит. */
export function NavItem({ to, icon: Icon, label, end, collapsed, onNavigate, active }: {
  to: string; icon: React.ComponentType<{ className?: string }>; label: string
  end?: boolean; collapsed?: boolean; onNavigate?: () => void; active?: boolean
}) {
  return (
    <SidebarMenuItem>
      <Tooltip>
        <TooltipTrigger asChild>
          <SidebarMenuButton asChild>
            <NavLink
              to={to}
              end={end}
              onClick={onNavigate}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  (active ?? isActive)
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

/**
 * Содержимое навигации сайдбара — без обёртки `<Sidebar>` из ui-кита.
 * Используется в двух контекстах:
 *  - десктоп: внутри `<Sidebar collapsible="icon">` (AppSidebar ниже);
 *  - мобильная шторка: напрямую в SheetContent (MainLayout). Класть сюда
 *    `<AppSidebar>` нельзя — ui-Sidebar на мобиле рендерит СВОЙ закрытый Sheet,
 *    и шторка получалась пустой.
 * `onNavigate` — колбэк на клик по пункту (мобила закрывает шторку).
 */
export function SidebarNavContent({ collapsed = false, onNavigate }: {
  collapsed?: boolean; onNavigate?: () => void
}) {
  const [dataOpen, setDataOpen] = useState(true)
  const [oneCOpen, setOneCOpen] = useState(false)   // 1С при запуске свёрнут
  const { company, companyModules, canApp, canModule } = useCompany()
  const { pathname, search } = useLocation()
  // Разделы рабочей области — здесь же, рядом со страницами продукта: рабочий стол
  // теперь уровнем выше (пространство), и внутри продукта верхний уровень навигации
  // принадлежит ему самому. Гармошка WorkspaceModeSidebar оставляет только под-разделы.
  const sections = useWorkspaceSections()
  // В продукте пространства («Финансы», «Данные», …) меню — только его разделы и
  // страницы: рабочее место не должно показывать чужие. Модулями Учёта пункты внутри не
  // фильтруются (у роли с ключом `finance` их нет, и «Документы» исчезли бы из
  // собственного продукта) — правами продукта фильтруются: `finance:files`.
  const product = isCarvedProfile(company.profileId) ? productForPath(pathname) : null
  if (product) {
    // Разделы берём фактические (useWorkspaceSections), а не объявленные в карте:
    // «Финансовый» и «Налоговый» сняты с витрины, и пункт вёл бы в пустоту.
    // Раздел, у которого все под-пункты закрыты ролью, приходит из хука пустым — такой
    // пункт не показываем, он открывал бы витрину без единого доступного экрана.
    // Право спрашиваем только у разделов, которые ЕСТЬ в карте прав («Финансы»,
    // «Данные»): у «Продаж» и «Проектов» правами гейтятся пункты внутри раздела, а
    // закрытый целиком раздел приходит из хука как `restricted` — этого достаточно.
    const modes = sections
      .filter((s) => product.modes.includes(s.mode))
      .filter((s) => !s.restricted && (!productHasModule(product.code, s.mode)
        || productModuleAllowed(product.code, s.mode, canModule)))
    const urlMode = new URLSearchParams(search).get('mode')
    const activeMode = modes.some((s) => s.mode === urlMode) ? urlMode : modes[0]?.mode
    const onProductRoute = pathname === product.route
    // Страницы («Документы», «Коннекторы») — тоже право: код = сегмент ИСХОДНОГО пути.
    const allowedPage = (code: string) => productModuleAllowed(product.code, code, canModule)
    const items = productNav(product, allowedPage, company.profileId)
    // Функции Ядра — одни на все рабочие места (`SPACE_PAGES`), поэтому отдельным блоком
    // ниже разделов и страниц продукта: сверху то, чем человек занят, ниже — пространство.
    const spaceItems = spaceNav(product, allowedPage)
    const links = SPACE_LINKS.filter(
      (l) => canApp(l.app) && productModuleAllowed(l.app, l.module, canModule))
    return (
      <>
        <SidebarGroup className="py-0">
          <SidebarMenu>
            {modes.map((s) => (
              <NavItem
                key={s.mode}
                to={`${product.route}?mode=${s.mode}`}
                icon={s.icon}
                label={s.label}
                collapsed={collapsed}
                onNavigate={onNavigate}
                active={onProductRoute && s.mode === activeMode}
              />
            ))}
            {items.map((item) => (
              <NavItem key={item.to} {...item} collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </SidebarMenu>
        </SidebarGroup>

        {(spaceItems.length > 0 || links.length > 0) && (
          <>
            <SidebarSeparator className="my-2" />
            <SidebarGroup className="py-0">
              {!collapsed && (
                <p className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-widest">
                  Пространство
                </p>
              )}
              <SidebarMenu>
                {[...spaceItems, ...links].map((item) => (
                  <NavItem key={item.to} to={item.to} icon={item.icon} label={item.label}
                    collapsed={collapsed} onNavigate={onNavigate} />
                ))}
              </SidebarMenu>
            </SidebarGroup>
          </>
        )}
      </>
    )
  }
  // Скрываем пункты, недоступные по модулям: права RBAC ∩ состав поставки из реестра
  // Ядра (см. CompanyContext). null = не ограничено.
  const allow = (to: string) => routeAllowed(to, companyModules)
  const mainNav = mainNavItems.filter((i) => allow(i.to))
  const dataNav = dataItems.filter((i) => allow(i.to))
  const oneCNav = oneCItems.filter((i) => allow(i.to))
  const settingsNav = settingsItems.filter((i) => allow(i.to))
  // Energy-профиль (РусГидро, сеть ЭЗС): нет 1С/топлива/FIFO/нормализации/закрытия —
  // эти разделы скрываем. Fuel-профиль (ГИГ) видит всё как прежде.
  const isEnergy = company.profileId === 'energy'
  // «Баланс ЭЗС» теперь модуль внутри режима «Управленческий» (ManagementPanel),
  // подключается к компании по профилю — отдельным пунктом левого меню больше не выводится.
  return (
    <>
      {/* Main nav */}
      {mainNav.length > 0 && (
        <SidebarGroup className="py-0">
          <SidebarMenu>
            {mainNav.map((item) => (
              <NavItem key={item.to} {...item} collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      )}

      {dataNav.length > 0 && <SidebarSeparator className="my-2" />}

      {/* ДАННЫЕ section (бывш. «Загрузка») */}
      {dataNav.length > 0 && (
      <SidebarGroup className="py-0">
        {collapsed ? (
          <SidebarMenu>
            <NavItem to={dataNav[0].to} icon={Layers} label="Данные" collapsed />
          </SidebarMenu>
        ) : (
          <Collapsible open={dataOpen} onOpenChange={setDataOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center justify-between w-full px-3 py-1.5 text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-widest hover:text-muted-foreground transition-colors">
                <span className="flex items-center gap-1.5">
                  <Layers className="h-3 w-3" />
                  Данные
                </span>
                <ChevronDown className={`h-3 w-3 transition-transform ${dataOpen ? '' : '-rotate-90'}`} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <SidebarMenu>
                {dataNav.map((item) => (
                  <NavItem key={item.to} {...item} collapsed={collapsed} onNavigate={onNavigate} />
                ))}
              </SidebarMenu>
            </CollapsibleContent>
          </Collapsible>
        )}
      </SidebarGroup>
      )}

      {/* 1С section — fuel-профиль (ГИГ) + доступ к модулю onec; energy (ЭЗС) без 1С */}
      {!isEnergy && oneCNav.length > 0 && (
        <>
          <SidebarSeparator className="my-2" />
          <SidebarGroup className="py-0">
            {collapsed ? (
              <SidebarMenu>
                <NavItem to="/1c/connection" icon={Database} label="1С" collapsed />
              </SidebarMenu>
            ) : (
              <Collapsible open={oneCOpen} onOpenChange={setOneCOpen}>
                <CollapsibleTrigger asChild>
                  <button className="flex items-center justify-between w-full px-3 py-1.5 text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-widest hover:text-muted-foreground transition-colors">
                    <span className="flex items-center gap-1.5">
                      <Database className="h-3 w-3" />
                      1С
                    </span>
                    <ChevronDown className={`h-3 w-3 transition-transform ${oneCOpen ? '' : '-rotate-90'}`} />
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <SidebarMenu>
                    {oneCNav.map((item) => (
                      <NavItem key={item.to} {...item} collapsed={collapsed} onNavigate={onNavigate} />
                    ))}
                  </SidebarMenu>
                </CollapsibleContent>
              </Collapsible>
            )}
          </SidebarGroup>
        </>
      )}

      <SidebarSeparator className="my-2" />

      {/* Settings */}
      {settingsNav.length > 0 && (
      <SidebarGroup className="py-0">
        {!collapsed && (
          <p className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-widest">
            Настройки
          </p>
        )}
        <SidebarMenu>
          {settingsNav.map((item) => (
            <NavItem key={item.to} {...item} collapsed={collapsed} onNavigate={onNavigate} />
          ))}
        </SidebarMenu>
      </SidebarGroup>
      )}

      {/* Администрирование вынесено из Ledger в отдельное приложение «Центр управления»
          (плитка на рабочем столе экосистемы). У приложений-продуктов своей админки нет. */}
    </>
  )
}

export function AppSidebar() {
  const { state, toggleSidebar } = useSidebar()
  const collapsed = state === 'collapsed'

  return (
    <Sidebar collapsible="icon" className="border-r border-border/40 pt-[var(--header-height)] pb-12">
      <SidebarContent data-zone="Навигация приложения" data-zone-side className="px-1.5 py-1">
        {/* Toggle button */}
        <div className={`flex ${collapsed ? 'justify-center' : 'justify-end'} px-1 py-1.5`}>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar}
            title={collapsed ? 'Развернуть' : 'Свернуть'}>
            {collapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <PanelLeftClose className="h-3.5 w-3.5" />}
          </Button>
        </div>

        <SidebarNavContent collapsed={collapsed} />
      </SidebarContent>

      <SidebarFooter />
    </Sidebar>
  )
}
