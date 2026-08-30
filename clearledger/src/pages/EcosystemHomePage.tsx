/**
 * Рабочий стол экосистемы — стартовый экран Ядра (docs/CORE.md §2). Вход приземляется
 * СЮДА, а не в Ledger: экосистема — это набор слоёв, а не одно приложение.
 *
 * Три слоя (сверху вниз):
 *   1. Центр управления — /admin (реестр приложений, RBAC, аудит, компании). Админам.
 *   2. Сервисы экосистемы — универсальные сервисы КОНТЕЙНЕРА (Чат/Заявки/Конференции):
 *      один на всю экосистему, потребляются всеми приложениями. Здесь — самостоятельный
 *      вход; второй вход в тот же сервис — кнопка внутри приложения (напр. чат в Ledger).
 *   3. Приложения — продукты экосистемы (Ledger со своими модулями, Support).
 *
 * Классификация слоя приходит с бэкенда (`layer` в /api/sso/apps), не хардкодится по коду.
 */
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Menu, LayoutGrid, ExternalLink, Loader2,
  LifeBuoy, ClipboardList, ListChecks, Video, FileText, MessagesSquare,
  ShieldCheck, BookOpen, HardHat, Gauge, BarChart3, Wallet, Database, MessageCircle,
  Building2, ShoppingCart, Megaphone, Network, Calculator, Stethoscope, Activity,
  Briefcase, Bot,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { HeaderUserMenu } from '@/components/layout/HeaderUserMenu'
import { MobileContextBar } from '@/components/layout/MobileContextBar'
import { MobileShell } from '@/components/common/MobileShell'
import { HeaderInteractionButtons } from '@/components/layout/HeaderInteractionButtons'
import { CompanySelector } from '@/components/company/CompanySelector'
import { ECOSYSTEM_BRAND } from '@/config/brand'
import { InteractionModal } from '@/components/support/InteractionModal'
import { SidebarNavContent } from '@/components/layout/AppSidebar'
import { SidebarProvider } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { listSsoApps, type SsoApp } from '@/services/ssoService'
import { listPartnerSpaces, visitPartnerSpace } from '@/services/partnerSpaceService'
import { useOpenApp } from '@/hooks/useOpenApp'
import {
  READINESS_LABEL, SPACE_PRODUCTS, productReadiness, type Readiness,
} from '@/config/spaceProducts'


/** Иконка по имени из реестра Ядра (`eco_apps.icon`, манифест `apps/<code>.yml`).
 *  Неизвестное имя — LayoutGrid: плитка появляется, просто без своего значка. */
const ICONS: Record<string, typeof FileText> = {
  'life-buoy': LifeBuoy,
  'clipboard-list': ClipboardList,
  'list-checks': ListChecks,
  'video': Video,
  'file-text': FileText,
  'messages-square': MessagesSquare,
  'message-circle': MessageCircle,
  'shield-check': ShieldCheck,
  'book-open': BookOpen,
  'activity': Activity,
  // Продукты разреза Учёта (config/spaceProducts.ts).
  'hard-hat': HardHat,
  'gauge': Gauge,
  'bar-chart-3': BarChart3,
  'wallet': Wallet,
  'database': Database,
  'building-2': Building2,
  'shopping-cart': ShoppingCart,
  'megaphone': Megaphone,
  'network': Network,
  'calculator': Calculator,
  'stethoscope': Stethoscope,
  // Рабочие места компании без объектов: «Услуги». «Бухгалтерия» и «Продажи» берут
  // book-open и bar-chart-3 — они выше. Незнакомое имя молча даёт LayoutGrid.
  'briefcase': Briefcase,
  // Аудитор — сквозной агент пространства.
  'bot': Bot,
}

interface TileProps {
  title: string
  subtitle: string
  icon: typeof FileText
  badge?: string
  availability?: string
  busy?: boolean
  inactive?: boolean
  readiness?: Readiness
  onClick: () => void
}

/** Точка готовности: зелёная — рабочий, жёлтая — в развитии, красная — в подключении. */
const DOT_CLASS: Record<Readiness, string> = {
  ready: 'bg-emerald-500',
  partial: 'bg-amber-400',
  draft: 'bg-red-500',
}

/**
 * Приложения клиентской стороны: продать, обслужить, поддержать. Остальные продукты —
 * внутренний контур (стройка сети, эксплуатация, связь, деньги). Деление по контуру,
 * а не по слою: слой говорит, ЧТО это (ядро/сервис/приложение), контур — про чей день.
 */
// Рабочая строка стола. Порядок — как к продуктам обращаются за день: заявки,
// продажи, расчёты, товары, продвижение и состояние систем (решение МАГа
// 01.08.2026; отменяет вынос «Поддержки» в сервисы от 31.07.2026 — заявки
// оказались началом дня, а не общей утилитой вроде чата).
const COMMERCE_APPS = [
  'support', 'revenue', 'corp', 'retail_store', 'monitor',
]
// «Пульс» — рабочее место руководителя над ВСЕМ пространством, поэтому своя строка
// вверху стола, а не «чем владеем и как считаем» (ecosystem-deploy/docs/PULSE.md).
// Круг узкий: у кого права нет, тот этой строки не увидит вовсе.
const LEAD_APPS = ['pulse']
const OPERATIONS_APPS = ['projects', 'ops', 'netlink', 'diag']
const SERVICE_APPS = ['chat', 'docs', 'conf', 'shop', 'marketing']
/**
 * Карточка продукта: имя, точка готовности и короткое пояснение.
 *
 * Показатели с плитки убраны (решение МАГа 01.08.2026). Стол — это вход в продукт,
 * а не сводка: цифры отвечали на случайные вопросы, у каждого продукта на свой лад,
 * и при этом не помещались — «11 240 заявок» показывалось как «11 …».
 *
 * Пояснение берётся из реестра приложений; полный текст остаётся в подсказке плитки.
 *
 * На телефоне плитка складывается в ОДНУ строку — имя во всю ширину. Двухэтажная
 * карточка занимала 99 px, и до нижних продуктов приходилось листать три экрана.
 */
function Tile({
  title, subtitle, icon: Icon, badge, availability, busy, inactive, readiness, onClick,
}: TileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || inactive}
      title={[title, availability, subtitle, badge, readiness && READINESS_LABEL[readiness]]
        .filter(Boolean).join(' · ')}
      className={`group relative flex h-full min-h-12 snap-start items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left
                  transition-colors duration-200 sm:min-h-0 sm:flex-col sm:items-stretch sm:gap-2
                  ${inactive
                    ? 'cursor-inherit border-dashed border-border bg-card'
                    : 'border-primary/30 bg-primary/[0.08] hover:border-primary/50 hover:bg-primary/[0.14]'}
                  ${busy ? 'opacity-60' : ''}`}
    >
      {/* Имя продукта. Готовность — точка в конце строки, а не абсолютом в углу:
          в потоке она занимает своё место и не наезжает на длинное название. */}
      <span className="flex min-w-0 flex-1 items-center gap-2.5 sm:w-full sm:flex-none">
        <span className={`shrink-0 rounded-lg p-1.5 transition-colors
                         ${inactive
                           ? 'bg-muted text-muted-foreground'
                           : 'bg-primary/15 text-primary group-hover:bg-primary group-hover:text-primary-foreground'}`}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium leading-snug">{title}</span>
        {availability && (
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium sm:hidden
                           ${inactive
                             ? 'border border-dashed border-border bg-card text-muted-foreground'
                             : 'bg-primary text-primary-foreground'}`}>
            {availability}
          </span>
        )}
        {/* Свой вход — значком, а не подписью: важен при первом знакомстве, а места
            в строке занимает как буква. Расшифровка — в подсказке всей плитки. */}
        {badge && <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />}
        {readiness && (
          <span aria-hidden="true"
            className={`size-2 shrink-0 rounded-full ${DOT_CLASS[readiness]}`} />
        )}
      </span>
      {/* Пояснение вместо показателей (решение МАГа 01.08.2026): цифры на столе
          читались как сводка, но отвечали на случайные вопросы и жили своей жизнью
          от продукта к продукту. Стол — это вход, а не отчёт. Две строки максимум:
          третья уводит плитку в высоту, полный текст лежит в подсказке. */}
      <span className="hidden text-[11px] leading-snug text-muted-foreground/90
                       sm:line-clamp-2 sm:border-t sm:border-border/60 sm:pt-2">
        {availability && (
          <span className={`font-medium ${inactive ? 'text-muted-foreground' : 'text-primary'}`}>
            {availability} ·{' '}
          </span>
        )}
        {subtitle}
      </span>
    </button>
  )
}

/**
 * Слой стола: подпись слева, плитки справа. Заголовок отдельной строкой стоил трёх
 * строк высоты на каждый слой — при трёх слоях это уже экран. Карточки держатся одной
 * строкой на любой ширине; если строка не помещается, прокручивается только этот слой.
 */
function Section({ title, hint, children, divider }: {
  title: string; hint?: string; children: React.ReactNode
  /** Линия сверху — граница уровня стола (Ядро · Сервисы · Приложения). */
  divider?: boolean
}) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef({
    active: false, moved: false, pointerId: -1, startX: 0, startScrollLeft: 0,
  })

  function startDrag(event: React.PointerEvent<HTMLDivElement>) {
    const scroller = scrollerRef.current
    if (event.pointerType !== 'mouse' || event.button !== 0
      || !scroller || scroller.scrollWidth <= scroller.clientWidth) return
    dragRef.current = {
      active: true,
      moved: false,
      pointerId: event.pointerId,
      startX: event.clientX,
      startScrollLeft: scroller.scrollLeft,
    }
  }

  function moveDrag(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag.active || drag.pointerId !== event.pointerId) return
    const distance = event.clientX - drag.startX
    if (!drag.moved && Math.abs(distance) < 5) return
    if (!drag.moved) {
      drag.moved = true
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    event.currentTarget.scrollLeft = drag.startScrollLeft - distance
    event.preventDefault()
  }

  function finishDrag(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag.active || drag.pointerId !== event.pointerId) return
    drag.active = false
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    window.setTimeout(() => { drag.moved = false }, 0)
  }

  function suppressClickAfterDrag(event: React.MouseEvent<HTMLDivElement>) {
    if (!dragRef.current.moved) return
    event.preventDefault()
    event.stopPropagation()
    dragRef.current.moved = false
  }

  return (
    <section className={`grid min-w-0 gap-x-4 gap-y-2 md:grid-cols-[116px_minmax(0,1fr)]
                         ${divider ? 'border-t border-border/60 pt-4' : ''}`}>
      <div className="md:pt-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">{title}</h2>
        {hint && <p className="mt-0.5 hidden text-[11px] text-muted-foreground/50 md:block">{hint}</p>}
      </div>
      <div
        ref={scrollerRef}
        role="region"
        aria-label={`${title}: приложения`}
        tabIndex={0}
        onPointerDownCapture={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        onClickCapture={suppressClickAfterDrag}
        onDragStart={(event) => event.preventDefault()}
        className="grid min-w-0 snap-x snap-proximity grid-flow-col auto-cols-[minmax(300px,330px)]
                   cursor-grab select-none gap-2 overflow-x-auto overscroll-x-contain pb-2 pr-1 active:cursor-grabbing
                   sm:auto-cols-[minmax(208px,244px)]"
      >
        {children}
      </div>
    </section>
  )
}

function DemoAccessLegend() {
  return (
    <div
      className="flex shrink-0 flex-col gap-2 rounded-xl border border-border/70 bg-card/50 px-3 py-2.5
                 text-xs text-muted-foreground sm:flex-row sm:items-center sm:gap-5"
      aria-label="Доступность приложений в демонстрации"
    >
      <span className="flex items-center gap-2">
        <span className="shrink-0 whitespace-nowrap rounded-full bg-primary px-2 py-0.5 font-medium text-primary-foreground">
          Открыть здесь
        </span>
        <span>можно нажать и посмотреть в этом демо</span>
      </span>
      <span className="flex items-center gap-2">
        <span className="shrink-0 whitespace-nowrap rounded-full border border-dashed border-border px-2 py-0.5 font-medium text-foreground">
          Отдельное демо
        </span>
        <span>приложение можно подключить к компании, здесь оно не открывается</span>
      </span>
    </div>
  )
}

export function EcosystemHomePage({ embedded, onNavigate }: {
  /** Встроенный вид: без шапки стола и приветствия — сетка живёт в чужой области. */
  embedded?: boolean
  /** Дать знать хозяину области, что человек ушёл в приложение (закрыть панель). */
  onNavigate?: () => void
} = {}) {
  const navigate = useNavigate()
  const location = useLocation()
  // Ссылки на разделы рабочей области (`/?mode=projects&sub=pr_project&project=…`)
  // приземлялись на стол: `?mode=` читает область продукта, а не он. Уводим на адрес
  // продукта со всеми параметрами — иначе письмо «вы в составе проекта» открывает стол.
  useEffect(() => {
    if (location.pathname !== '/') return
    const mode = new URLSearchParams(location.search).get('mode')
    const target = mode && SPACE_PRODUCTS.find((p) => (p.modes as string[]).includes(mode))
    if (target) navigate(`${target.route}${location.search}`, { replace: true })
  }, [location, navigate])
  const [menuOpen, setMenuOpen] = useState(false)
  const { user } = useAuth()
  const { company, companyId } = useCompany()
  // Открытие продуктов — общей логикой с лаунчером: там же живёт особый случай
  // «Конференций», где вместо перехода на чужую главную создаётся комната.
  const { open: openViaHook, busy } = useOpenApp()

  const q = useQuery({
    queryKey: ['sso-apps', companyId],
    queryFn: () => listSsoApps(companyId),
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  // RBAC-гейт стола: allowed_apps — коды, доступных ролью в компании (null = не ограничено,
  // напр. админ). Бэкенд уже отфильтровал apps; здесь гейтим внутренние плитки Ledger и Чат.
  const allowed = q.data?.allowed_apps ?? null
  const canOpen = (code: string) => allowed === null || allowed.includes(code)
  const all: SsoApp[] = (q.data?.apps ?? []).filter((a) => canOpen(a.code))
  // Слой каталога говорит, ЧТО это (ядро/сервис/приложение), но место на столе
  // задаёт рабочий контур: «Поддержка» числится сервисом, «Диагностика» — ядром,
  // а работают с ними в общей строке дня (решение МАГа 01.08.2026).
  const management = all.filter((a) => a.layer === 'admin' && !COMMERCE_APPS.includes(a.code))
  const services = [
    ...SERVICE_APPS.map((code) => all.find((a) => a.code === code))
      .filter((a): a is SsoApp => !!a),
    ...all.filter((a) => a.layer === 'service' && !COMMERCE_APPS.includes(a.code)
      && !SERVICE_APPS.includes(a.code)),
  ]
  const apps = all.filter((a) => !SERVICE_APPS.includes(a.code) && (COMMERCE_APPS.includes(a.code)
    || (a.layer !== 'admin' && a.layer !== 'service')))
  // Два контура приложений: обращённый к клиенту (продать, обслужить) и внутренний
  // (построить, содержать, посчитать).
  const lead = apps.filter((a) => LEAD_APPS.includes(a.code))
  // Порядок рабочей строки задан явно, а не порядком реестра: он отражает,
  // в каком порядке к продуктам обращаются в течение дня.
  const commerce = COMMERCE_APPS
    .map((code) => apps.find((a) => a.code === code))
    .filter((a): a is SsoApp => !!a)
  const operations = OPERATIONS_APPS
    .map((code) => apps.find((a) => a.code === code))
    .filter((a): a is SsoApp => !!a)
  // Учётная строка: содержание сети и деньги за неё — в том порядке, в каком
  // цифра идёт от объекта к отчётности.
  const INTERNAL_ORDER = ['econ', 'perimeter', 'books']
  const internal = apps
    .filter((a) => !COMMERCE_APPS.includes(a.code) && !LEAD_APPS.includes(a.code)
      && !OPERATIONS_APPS.includes(a.code))
    .sort((a, b) => {
      const ia = INTERNAL_ORDER.indexOf(a.code), ib = INTERNAL_ORDER.indexOf(b.code)
      // Незаданные продукты идут следом за перечисленными, порядком реестра.
      return (ia < 0 ? INTERNAL_ORDER.length : ia) - (ib < 0 ? INTERNAL_ORDER.length : ib)
    })

  /**
   * Открыть продукт. Продукт пространства — это СТРАНИЦА, и открывается он обычным
   * переходом в текущей вкладке (решение МАГа 21.08.2026, отменяет прежний порядок
   * от 27.07.2026, когда каждый продукт уходил в новую вкладку).
   *
   * Почему отменено: вкладки копились десятками, «назад» вело не туда, откуда
   * пришли, а на пустой стол в другой вкладке, и одно пространство размазывалось по
   * всему окну браузера. Адрес продукта и так свой — им и делятся, когда нужно
   * второе окно; браузер для этого умеет «открыть в новой вкладке» сам, и это
   * решение человека, а не приложения.
   *
   * Внешние приложения (свой домен, свой вход) по-прежнему уходят в новую вкладку:
   * там чужая сессия и чужой «назад», и возвращать человека оттуда нам нечем.
   */
  async function openProduct(app: SsoApp) {
    if (app.mode === 'internal' && app.route) {
      navigate(app.route)
      onNavigate?.()
      return
    }
    await openExternal(app)
  }

  /** Открыть внешнее приложение: SSO — по handoff-токену, мост — ссылкой.
   *
   *  Вкладку не навязываем: приложение стека («Поддержка» на /support) живёт на
   *  том же домене и для человека это такая же страница пространства, что и
   *  внутренние продукты, — а принудительная вкладка открывала его отдельным
   *  окном. Чужой домен уходит в новую вкладку всегда: там своя сессия и свой
   *  «назад», и это решает сам хук по origin. */
  async function openExternal(app: SsoApp) {
    await openViaHook(app.code)
  }

  /** Плитка любого продукта пространства: подпись говорит, ЧТО за ним стоит, а не как он
   *  откроется. Способ входа виден значком «вход отдельный» в углу, а пока подпись занимала
   *  «Открывается по ссылке», описание из реестра не доходило до человека вовсе — и
   *  «Конференции» молчали о том, что вход без регистрации, прямо в браузере. */
  // Пространства клиентов: инженер входит туда СВОЕЙ учётной записью, пропуском.
  // Стол — единственное место, где это уместно: вход к заказчику не раздел учёта и
  // не настройка контейнера, а такой же переход, как открыть приложение.
  const partnerSpaces = useQuery({
    queryKey: ['partner-spaces', company.id],
    queryFn: () => listPartnerSpaces(company.id),
    enabled: isApiEnabled() && !!company.id,
    staleTime: 5 * 60_000,
  })
  const clientSpaces = (partnerSpaces.data?.items || [])
    .filter((p) => p.role === 'client' && p.isActive && p.linked)
  const [visiting, setVisiting] = useState<string | null>(null)

  async function openSpace(code: string) {
    setVisiting(code)
    try {
      const res = await visitPartnerSpace(code, company.id)
      // Пропуск живёт две минуты — открываем сразу, «на потом» он не годится.
      window.location.href = res.url
    } catch (e) {
      setVisiting(null)
      toast.error('Не удалось войти', { description: (e as Error).message })
    }
  }

  function renderProductTile(a: SsoApp) {
    const isOptional = a.mode === 'internal' && !a.route
    const description = a.description
      || (a.mode === 'internal' ? 'Продукт пространства'
        : a.mode === 'link' ? 'Открывается по ссылке' : 'Единый вход')
    const subtitle = isOptional ? `Можно подключить · ${description}` : description
    return (
      <Tile
        key={a.code}
        title={a.name}
        subtitle={subtitle}
        icon={ICONS[a.icon] ?? LayoutGrid}
        badge={a.mode === 'link' ? 'вход отдельный' : undefined}
        availability={isOptional ? 'Отдельное демо' : 'Открыть здесь'}
        busy={busy === a.code}
        inactive={isOptional}
        readiness={isOptional ? undefined : productReadiness(a.code, company.profileId)}
        onClick={() => openProduct(a)}
      />
    )
  }

  /**
   * Стол демонстрационного стенда.
   *
   * Рабочий стол показывает всё, чем компания пользуется, — плитки равнозначны, и
   * это правильно для того, кто здесь работает. Человеку, которому показывают
   * систему впервые, такой стол не отвечает на единственный его вопрос: с чего
   * начать. Поэтому на стенде тот же каталог подан тремя зонами разного веса:
   * что ставим сейчас, что идёт в комплекте, что можно добавить потом.
   *
   * Зоны считаются по данным, а не по списку кодов: «идёт в комплекте» — это
   * продукт с рабочим маршрутом в этом стеке, «можно добавить» — заведённый в
   * реестре, но без экранов. Список кодов разошёлся бы с составом стека на первой
   * же выкатке.
   */
  function renderStandLayers() {
    const optional = (a: SsoApp) => a.mode === 'internal' && !a.route
    const monitor = all.find((a) => a.code === 'monitor')
    const included = all.filter((a) => !optional(a) && a.code !== 'monitor')
    const later = all.filter(optional)
    return (
      <>
        <div className="mb-5 rounded-xl border border-primary/25 bg-primary/[0.06] p-4 sm:p-5">
          <h2 className="text-base font-semibold sm:text-lg">
            Единое пространство компании
          </h2>
          <p className="mt-1.5 max-w-3xl text-sm text-muted-foreground">
            Один вход, одни люди и права, одна переписка — а продукты подключаются
            по одному, когда нужны. Сейчас предлагается само пространство, в котором
            вы находитесь, и «Монитор» — панель сети АЗС.
          </p>
          {monitor && (
            <Button className="mt-3.5" onClick={() => openProduct(monitor)}
                    disabled={busy === monitor.code}>
              Открыть «Монитор»
            </Button>
          )}
        </div>
        <Section title="Уже внутри"
                 hint="идёт вместе с пространством — подключать ничего не нужно">
          {included.map(renderProductTile)}
        </Section>
        {later.length > 0 && (
          <Section title="Можно добавить позже"
                   hint="продукты экосистемы: по одному, когда понадобятся" divider>
            {later.map(renderProductTile)}
          </Section>
        )}
      </>
    )
  }

  /** Слои продуктов — общая часть стола и встроенной панели «Приложения». */
  function renderLayers() {
    // Стенд узнаётся по базовому пути сборки: пространство отдаётся кабинетом
    // сайта под /demo-run/<стенд>/app/, и другого признака показа не нужно.
    if (import.meta.env.BASE_URL.startsWith('/demo-run/')) return renderStandLayers()
    return (
      <>
        {lead.length > 0 && (
          <Section title="Руководство" hint="как идут дела и куда вмешаться">
            {lead.map(renderProductTile)}
          </Section>
        )}
        {commerce.length > 0 && (
          <Section title="Клиенты и продажи" hint="кому продаём и как обслуживаем" divider={lead.length > 0}>
            {commerce.map(renderProductTile)}
          </Section>
        )}
        <Section title="Учёт" hint="экономика, периметр и бухгалтерия" divider>
          {internal.map(renderProductTile)}
          {q.isLoading && (
            <div className="flex items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Загрузка каталога…
            </div>
          )}
          {!q.isLoading && apps.length === 0 && (
            <div className="px-3 py-2.5 text-sm text-muted-foreground">
              Приложения не подключены. Состав задаётся в «Управлении» → «Приложения».
            </div>
          )}
        </Section>
        {operations.length > 0 && (
          <Section title="Сеть" hint="связь, оборудование и состояние систем" divider>
            {operations.map(renderProductTile)}
          </Section>
        )}
        {services.length > 0 && (
          <Section title="Сервисы экосистемы" hint="общие для всех приложений" divider>
            {services.map(renderProductTile)}
          </Section>
        )}
        {clientSpaces.length > 0 && (
          <Section title="Пространства клиентов" hint="войти своей учётной записью" divider>
            {clientSpaces.map((p) => (
              <Tile
                key={p.code}
                title={p.name}
                subtitle="Рабочее пространство клиента"
                icon={Network}
                availability="Войти по пропуску"
                busy={visiting === p.code}
                onClick={() => openSpace(p.code)}
              />
            ))}
          </Section>
        )}
        {management.length > 0 && (
          <Section title="Ядро системы" divider>
            {management.map(renderProductTile)}
          </Section>
        )}
      </>
    )
  }

  // Встроенный вид: сетка внутри чужой рабочей области. Шапки и приветствия нет —
  // человек не уходил со своего экрана, он открыл меню приложений поверх него.
  if (embedded) {
    return (
      <div className="flex w-full flex-col gap-5 px-4 py-4 sm:px-6">
        <DemoAccessLegend />
        {renderLayers()}
      </div>
    )
  }

  return (
    // Стол занимает ровно экран и сам не прокручивается: это витрина пространства,
    // а не документ. Прокрутку получает только слой приложений, если продуктов станет
    // больше, чем помещается (docs/SPACE.md §1 — состав приложений открыт).
    <div className="flex h-dvh flex-col overflow-hidden bg-background">
      <header className="flex h-header shrink-0 items-center justify-between gap-4 border-b border-border px-4 sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          {/* Основное меню — в левом верхнем углу, как в любом приложении
              пространства. Стол живёт вне общего каркаса, поэтому шторку он
              держит свою, но содержимое то же самое (SidebarNavContent). */}
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="shrink-0 sm:hidden" title="Меню">
                <Menu className="size-5" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="p-0 w-72 mobile-safe-left">
              <SheetTitle className="sr-only">Меню навигации</SheetTitle>
              <SheetDescription className="sr-only">Разделы пространства</SheetDescription>
              {/* SidebarProvider обязателен: пункты меню строятся на SidebarMenuButton,
                  а тот зовёт useSidebar. В приложениях провайдер даёт MainLayout, у
                  стола его нет — без обёртки нажатие бургера роняло экран. */}
              <SidebarProvider>
                <div className="h-full w-full overflow-y-auto px-1.5 py-3">
                  <SidebarNavContent onNavigate={() => setMenuOpen(false)} />
                </div>
              </SidebarProvider>
            </SheetContent>
          </Sheet>
          {/* Знак пространства — тот же файл, что в шапке приложений и во вкладке
              браузера (сборка кладёт его в `favicon.svg` по бренду стека). Здесь
              стоял общий значок-сетка, и рабочий стол — первый экран, куда человек
              попадает, — оставался единственным местом без знака компании. */}
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt=""
            className="hidden size-9 shrink-0 rounded-xl sm:inline-block" />
          {/* Слева — имя ПРОСТРАНСТВА, а не организации. Здесь стояло имя организации,
              и стол называл себя «ПРОМИЗОЛ СПБ», хотя это пространство «Аудит», внутри
              которого организаций может быть много. Организацию называет переключатель;
              путать эти два уровня нельзя (замечание МАГа 15.08.2026). */}
          <div className="hidden min-w-0 sm:block">
            <div className="truncate font-semibold leading-tight">{ECOSYSTEM_BRAND}</div>
            <div className="truncate text-xs text-muted-foreground">Рабочее пространство</div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-3">
          {/* Переключатель организации — там же, где в приложениях: в шапке, слева от
              «Конференции». Место одно на всё пространство, куда бы человек ни зашёл. */}
          <span className="hidden sm:inline-flex"><CompanySelector /></span>
          {/* Чат · Заявки · Конференция — тот же блок, что в шапке приложений:
              связь с пространством лежит на одном месте, куда бы человек ни зашёл. */}
          <HeaderInteractionButtons conference />
          {/* Профиль иконкой — как в приложениях пространства: выход, тема,
              уведомления и версия лежат внутри, а не отдельными кнопками. */}
          <HeaderUserMenu settingsPath="/settings" />
        </div>
      </header>

      {/* Организация и юрлицо — строкой ниже и слева: в шапке они конкурировали
          за место с кнопками связи и профилем. Полоса одна на всё пространство. */}
      <MobileContextBar />

      {/* Ширину не режем до 1024: на широком экране это выталкивало продукты вниз
          при пустых полях по бокам. Предел нужен лишь чтобы строка плиток не
          растягивалась бесконечно на панорамных мониторах. */}
      {/* Прокручивается вся область стола, а не один слой: слоёв четыре, продуктов
          двенадцать и число их растёт — при нехватке высоты верхние слои иначе просто
          обрезаются, и добраться до них нечем. Шапка остаётся на месте. */}
      <MobileShell className="mx-auto flex w-full min-h-0 max-w-[1600px] flex-1 flex-col gap-5
                             overflow-y-auto px-4 py-5 sm:px-8">
        {/* Приветствие — одна строка: компания уже названа в шапке, повторять её
            отдельным абзацем значит занять высоту ради того же слова. */}
        <h1 className="shrink-0 text-lg font-semibold">
          {user?.name ? `Здравствуйте, ${user.name}` : 'Рабочий стол'}
        </h1>

        <DemoAccessLegend />

        {/* Все слои — из ОДНОГО каталога продуктов пространства (`Layers`), тем же
            составом, что и панель «Приложения» в рабочей области приложений. */}
        {renderLayers()}
      </MobileShell>

      {/* Окно «Взаимодействие» — то же, что открывают кнопки шапки в приложениях.
          Стол живёт вне AdminLayout, который его монтирует, и без этой строки
          кнопки Чат/Задачи/Инфо переключали состояние вхолостую: подсвечивались,
          но рисовать окно было некому. Док сюда не берём — рейла на столе нет. */}
      <InteractionModal />
    </div>
  )
}
