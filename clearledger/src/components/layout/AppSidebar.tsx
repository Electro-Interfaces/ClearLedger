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
  Archive, Megaphone, MessagesSquare, UserRound, Users2,
  BookOpen, Compass, Scale, FileSignature, HelpCircle,
  Activity, TrendingUp, Users, CalendarDays, LayoutDashboard,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useCompany } from '@/contexts/CompanyContext'
import { mainNavItems, dataItems, oneCItems, settingsItems, navByPath } from '@/config/navigation'
import { routeAllowed } from '@/config/accessModules'
import {
  SPACE_LINKS, SPACE_PAGES, isCarvedProfile, isOneCPath, productForPath, productNav, spaceNav,
} from '@/config/spaceProducts'
import { productModuleAllowed, productHasModule } from '@/config/productAccess'
import { useWorkspaceSections } from '@/components/workspace/workspaceSections'
import { useActiveMode } from '@/contexts/ActiveModeContext'

/** Пункт левого меню. Общий для Учёта и Управления — вид навигации один на приложения.
 *  `active` — переопределить подсветку: у разделов рабочей области адрес один и тот же,
 *  различает их параметр `?mode=`, которого NavLink не видит. */
export function NavItem({ to, icon: Icon, label, end, collapsed, onNavigate, active }: {
  to: string; icon: React.ComponentType<{ className?: string }>; label: string
  end?: boolean; collapsed?: boolean; onNavigate?: () => void; active?: boolean
}) {
  // Активность считаем САМИ и передаём готовой строкой классов.
  //
  // Функция-className у `NavLink` здесь не работает: кнопка обёрнута в
  // `SidebarMenuButton asChild`, а Slot склеивает свой класс с классом ребёнка
  // ДО того, как NavLink успеет вызвать функцию, — и в атрибут уезжает
  // исходный текст функции. Ни `isActive`, ни любой расчёт внутри неё до
  // страницы не доходили, поэтому выбранный раздел и не подсвечивался.
  //
  // Раздел узнаёт себя по `?mode=` в собственной ссылке против `?mode=` в
  // адресе — тот же приём, что в «Поддержке» (TSupport `itemActive`).
  const { pathname, search } = useLocation()
  const [toPath, toQuery] = to.split('?')
  const linkMode = new URLSearchParams(toQuery ?? '').get('mode')
  const urlMode = new URLSearchParams(search).get('mode')
  const pathActive = end
    ? pathname === toPath
    : pathname === toPath || pathname.startsWith(`${toPath}/`)
  const selected = linkMode
    ? (urlMode ? linkMode === urlMode : (active ?? pathActive))
    : (active ?? pathActive)

  return (
    <SidebarMenuItem>
      <Tooltip>
        <TooltipTrigger asChild>
          <SidebarMenuButton asChild>
            <NavLink
              to={to}
              end={end}
              onClick={onNavigate}
              // Выбранный раздел обязан отличаться от того, на что просто навели
              // мышь: у наведения свой фон, и при одинаковой силе заливки человек
              // не понимает, где находится. Отсюда более плотный фон, полужирное
              // начертание и вертикальный маркер слева.
              className={`relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                selected
                  ? 'bg-primary/15 font-semibold text-primary before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-0.5 before:rounded-full before:bg-primary'
                  : 'font-medium text-muted-foreground hover:bg-accent hover:text-foreground'
              } ${collapsed ? 'justify-center px-2' : ''}`}
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
/**
 * Разделы приложения «Чаты». Те же виды, которыми живёт сам чат: канал односторонний,
 * в группе говорят все, личный — про двоих. Архив отдельным пунктом, потому что это
 * другой вопрос: не «что происходит», а «что было».
 */
/**
 * Пласты знания - меню приложения «Инфо».
 *
 * Раньше на `/info` рисовалось меню Учёта целиком, и первым пунктом стоял «Рабочий
 * стол», уводивший из приложения совсем (решение МАГа 30.07.2026: пункт должен
 * оставлять человека там, где он есть). «Инфо» - самостоятельное приложение, его
 * верхний уровень навигации - пласты знания, а не чужие разделы.
 */
const INFO_VIEWS: { key: string; label: string; icon: typeof MessagesSquare }[] = [
  { key: 'all', label: 'Всё знание', icon: BookOpen },
  { key: 'guide', label: 'Работа в системе', icon: Compass },
  { key: 'norm', label: 'Нормы и требования', icon: Scale },
  { key: 'lnd', label: 'Документы компании', icon: FileSignature },
  { key: 'faq', label: 'Частые вопросы', icon: HelpCircle },
]

/** Разделы «Пульса»: у каждого свой вопрос, порядок — от срочного к обзорному. */
const PULSE_SECTIONS: { to: string; label: string; icon: typeof Activity }[] = [
  { to: '/pulse', label: 'Экран дня', icon: Activity },
  { to: '/pulse/business', label: 'Бизнес', icon: TrendingUp },
  { to: '/pulse/team', label: 'Команда', icon: Users },
  { to: '/pulse/week', label: 'Неделя', icon: CalendarDays },
]

const CHAT_VIEWS: { key: string; label: string; icon: typeof MessagesSquare }[] = [
  { key: 'all', label: 'Все чаты', icon: MessagesSquare },
  { key: 'channel', label: 'Каналы', icon: Megaphone },
  { key: 'group', label: 'Группы', icon: Users2 },
  { key: 'direct', label: 'Личные', icon: UserRound },
  { key: 'archive', label: 'Архив', icon: Archive },
]

/**
 * Меню приложения. Первым пунктом — выход на рабочий стол пространства.
 *
 * На десктопе к столу ведут логотип и кнопка «Стол» в шапке; на телефоне их нет
 * (шапка сведена к бургеру, имени экрана и связи), и без этого пункта из продукта
 * не было выхода вообще — ни назад к столу, ни в соседнее приложение.
 */
export function SidebarNavContent(props: { collapsed?: boolean; onNavigate?: () => void }) {
  const { pathname } = useLocation()
  return (
    <>
      {/* На самом столе пункт не нужен — человек уже там. */}
      {pathname !== '/' && (
        <SidebarGroup className="py-0">
          <SidebarMenu>
            <NavItem to="/" icon={LayoutDashboard} label="Рабочий стол" end
              collapsed={props.collapsed} onNavigate={props.onNavigate} />
          </SidebarMenu>
        </SidebarGroup>
      )}
      <SidebarNavBody {...props} />
    </>
  )
}

function SidebarNavBody({ collapsed = false, onNavigate }: {
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
  // Раздел, открытый рабочей областью прямо сейчас. Пока рельса угадывала его
  // по адресу, подсветка расходилась с экраном: открыт «Каталог», а выбранным
  // не выглядел никто.
  const { activeMode: openMode } = useActiveMode()
  // В продукте пространства («Финансы», «Данные», …) меню — только его разделы и
  // страницы: рабочее место не должно показывать чужие. Модулями Учёта пункты внутри не
  // фильтруются (у роли с ключом `finance` их нет, и «Документы» исчезли бы из
  // собственного продукта) — правами продукта фильтруются: `finance:files`.
  // Приложение «Чаты» — не продукт разреза, но полноценное рабочее место со своими
  // разделами: у управления перепиской те же виды, что и в самом чате (канал, группа,
  // личный) плюс архив. Без этой ветки экран открывался без левого меню — как страница,
  // а не как приложение.
  // «Пульс» — рабочее место руководителя (ecosystem-deploy/docs/PULSE.md §3): четыре
  // раздела, разные вопросы одного дня. «Экран дня» — что требует вмешательства прямо
  // сейчас; «Бизнес» — как идут дела вообще; «Команда» — у кого затор; «Неделя» — итоги.
  if (pathname === '/pulse' || pathname.startsWith('/pulse/')) {
    // Блок Ядра — как в любом рабочем месте (SPACE.md §4): функции пространства
    // одинаковы везде, и руководителю они нужны не меньше (посмотреть объект,
    // договор, людей и доступы). Ведут на общие адреса — «Пульс» их не присваивает.
    const spaceItems = SPACE_PAGES
      .filter((p) => navByPath[p])
      .map((p) => navByPath[p])
    return (
      <>
        <SidebarGroup className="py-0">
          <SidebarMenu>
            {PULSE_SECTIONS.map((s) => (
              <NavItem key={s.to} to={s.to} icon={s.icon} label={s.label}
                collapsed={collapsed} onNavigate={onNavigate}
                active={pathname === s.to
                  || (s.to === '/pulse' && pathname === '/pulse/')} />
            ))}
          </SidebarMenu>
        </SidebarGroup>

        <SidebarSeparator className="my-2" />
        <SidebarGroup className="py-0">
          {!collapsed && (
            <p className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              Пространство
            </p>
          )}
          <SidebarMenu>
            {spaceItems.map((item) => (
              <NavItem key={item.to} to={item.to} icon={item.icon} label={item.label}
                collapsed={collapsed} onNavigate={onNavigate} />
            ))}
            {SPACE_LINKS.filter((l) => canApp(l.app)).map((l) => (
              <NavItem key={l.to} to={l.to} icon={l.icon} label={l.label}
                collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </>
    )
  }

  if (pathname === '/messages' || pathname.startsWith('/messages/')) {
    const view = new URLSearchParams(search).get('view') || 'all'
    return (
      <SidebarGroup className="py-0">
        <SidebarMenu>
          {CHAT_VIEWS.map((v) => (
            <NavItem key={v.key} to={`/messages${v.key === 'all' ? '' : `?view=${v.key}`}`}
              icon={v.icon} label={v.label} active={view === v.key} onNavigate={onNavigate} />
          ))}
        </SidebarMenu>
      </SidebarGroup>
    )
  }

  // «Инфо» - приложение Ядра со своим меню: пласты знания. Пункт ведёт на тот же
  // экран с фильтром, а не наружу: человек, открывший знание, остаётся в нём.
  if (pathname === '/info' || pathname.startsWith('/info/')) {
    const kind = new URLSearchParams(search).get('kind') || 'all'
    return (
      <SidebarGroup className="py-0">
        <SidebarMenu>
          {INFO_VIEWS.map((v) => (
            <NavItem key={v.key} to={`/info${v.key === 'all' ? '' : `?kind=${v.key}`}`}
              icon={v.icon} label={v.label} active={kind === v.key} onNavigate={onNavigate} />
          ))}
        </SidebarMenu>
      </SidebarGroup>
    )
  }

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
      .filter((s) => !s.restricted && (!productHasModule(product.code, s.mode, company.profileId)
        || productModuleAllowed(product.code, s.mode, canModule, company.profileId)))
    const params = new URLSearchParams(search)
    const urlMode = params.get('mode')
    const urlSub = params.get('sub')
    // Активный раздел ищем прежде всего по ОТКРЫТОМУ ПУНКТУ: во второй колонке
    // виден он, и подсветка обязана сойтись именно с ним. Дальше — режим из
    // адреса, и лишь в конце первый раздел (его же покажет рабочая область,
    // когда в адресе нет ничего).
    const bySub = urlSub ? modes.find((s) => s.items.some((i) => i.key === urlSub)) : undefined
    const activeMode = (openMode && modes.some((s) => s.mode === openMode) ? openMode : null)
      ?? bySub?.mode
      ?? (modes.some((s) => s.mode === urlMode) ? urlMode : modes[0]?.mode)
    // Разделы подсвечиваем везде, кроме страниц продукта («Объекты», «Документы»):
    // там открыт не раздел, а страница, и она подсветит себя сама. Сравнивать
    // путь с маршрутом точно нельзя — адрес приходит и с хвостовым слэшем.
    const onProductRoute = !SPACE_PAGES.some(
      (p) => pathname === `${product.route}${p}` || pathname.startsWith(`${product.route}${p}/`))
    // Страницы («Документы», «Коннекторы») — тоже право: код = сегмент ИСХОДНОГО пути.
    const allowedPage = (code: string) => productModuleAllowed(product.code, code, canModule, company.profileId)
    // Страницы продукта делятся надвое: своё рабочее (Организация) идёт сразу под
    // разделами, а контур обмена с 1С — двенадцать настроечных экранов — уезжает в
    // свёрнутую группу. Раньше они лежали одним списком с разделами, и половина
    // левого меню бухгалтера была настройкой обмена, а не его работой (04.08.2026).
    const allItems = productNav(product, allowedPage, company.profileId)
    const items = allItems.filter((i) => !isOneCPath(i.to))
    const oneCPages = allItems.filter((i) => isOneCPath(i.to))
    // Функции Ядра — одни на все рабочие места (`SPACE_PAGES`), поэтому отдельным блоком
    // ниже разделов и страниц продукта: сверху то, чем человек занят, ниже — пространство.
    const spaceItems = spaceNav(product, allowedPage)
    const links = SPACE_LINKS.filter(
      (l) => canApp(l.app) && productModuleAllowed(l.app, l.module, canModule, company.profileId))
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

        {oneCPages.length > 0 && (
          <>
            <SidebarSeparator className="my-2" />
            <SidebarGroup className="py-0">
              {collapsed ? (
                <SidebarMenu>
                  <NavItem to={oneCPages[0].to} icon={Database} label="Обмен с 1С" collapsed />
                </SidebarMenu>
              ) : (
                <Collapsible open={oneCOpen} onOpenChange={setOneCOpen}>
                  <CollapsibleTrigger asChild>
                    <button className="flex w-full items-center justify-between px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60 transition-colors hover:text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <Database className="h-3 w-3" />
                        Обмен с 1С
                      </span>
                      <ChevronDown className={`h-3 w-3 transition-transform ${oneCOpen ? '' : '-rotate-90'}`} />
                    </button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenu>
                      {oneCPages.map((item) => (
                        <NavItem key={item.to} {...item} collapsed={collapsed} onNavigate={onNavigate} />
                      ))}
                    </SidebarMenu>
                  </CollapsibleContent>
                </Collapsible>
              )}
            </SidebarGroup>
          </>
        )}

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
