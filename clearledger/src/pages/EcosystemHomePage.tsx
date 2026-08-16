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
import { useEffect, useState } from 'react'
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
import { listSsoApps, hasSideButton, isCoreApp, type SsoApp } from '@/services/ssoService'
import { useOpenApp } from '@/hooks/useOpenApp'
import { useMaxWidth } from '@/hooks/use-mobile'
import {
  READINESS_LABEL, SPACE_PRODUCTS, productReadiness, type Readiness,
} from '@/config/spaceProducts'

/** База сборки SPA (корень домена) — новая вкладка открывается по полному адресу. */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

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
  busy?: boolean
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
// продажи, стройка объектов, связь с ними и состояние систем (решение МАГа
// 01.08.2026; отменяет вынос «Поддержки» в сервисы от 31.07.2026 — заявки
// оказались началом дня, а не общей утилитой вроде чата).
const COMMERCE_APPS = [
  'support', 'sales', 'projects', 'netlink', 'diag',
  'shop', 'corp', 'marketing', 'monitor', 'processing',
]
// «Пульс» — рабочее место руководителя над ВСЕМ пространством, поэтому своя строка
// вверху стола, а не «чем владеем и как считаем» (ecosystem-deploy/docs/PULSE.md).
// Круг узкий: у кого права нет, тот этой строки не увидит вовсе.
const LEAD_APPS = ['pulse']
// Слой «Планы» — ниже ядра системы (решение МАГа 16.08.2026). Продукты заведены
// в реестре и когда-нибудь заработают, но сегодня в них нечего делать. Держать их
// среди рабочих значит каждый день предлагать человеку четыре двери, за которыми
// заставка: он перестаёт читать стол целиком.
//
// Список ведётся руками, а не по признаку готовности: «в подключении» бывает и у
// продукта, который вот-вот поедет, — решать, что показывать клиенту, должен
// человек, а не флаг в конфиге.
const PLANNED_APPS = ['netlink', 'diag', 'shop', 'corp', 'marketing']

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
function Tile({ title, subtitle, icon: Icon, badge, busy, readiness, onClick }: TileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      title={[title, subtitle, badge, readiness && READINESS_LABEL[readiness]]
        .filter(Boolean).join(' · ')}
      className="group relative flex h-full min-h-12 items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2.5 text-left
                 transition-colors duration-200 hover:border-primary/50 hover:bg-accent/40 disabled:opacity-60
                 sm:min-h-0 sm:flex-col sm:items-stretch sm:gap-2"
    >
      {/* Имя продукта. Готовность — точка в конце строки, а не абсолютом в углу:
          в потоке она занимает своё место и не наезжает на длинное название. */}
      <span className="flex min-w-0 flex-1 items-center gap-2.5 sm:w-full sm:flex-none">
        <span className="shrink-0 rounded-lg bg-primary/10 p-1.5 text-primary transition-colors group-hover:bg-primary group-hover:text-white">
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium leading-snug">{title}</span>
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
        {subtitle}
      </span>
    </button>
  )
}

/**
 * Слой стола: подпись слева, плитки справа. Заголовок отдельной строкой стоил трёх
 * строк высоты на каждый слой — при трёх слоях это уже экран. Сетка `auto-fill` сама
 * набирает столько колонок, сколько влезает, поэтому широкий экран показывает слой
 * одной строкой, а узкий — переносит.
 */
function Section({ title, hint, children, divider }: {
  title: string; hint?: string; children: React.ReactNode
  /** Линия сверху — граница уровня стола (Ядро · Сервисы · Приложения). */
  divider?: boolean
}) {
  return (
    <section className={`grid gap-x-4 gap-y-2 md:grid-cols-[116px_1fr]
                         ${divider ? 'border-t border-border/60 pt-4' : ''}`}>
      <div className="md:pt-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">{title}</h2>
        {hint && <p className="mt-0.5 hidden text-[11px] text-muted-foreground/50 md:block">{hint}</p>}
      </div>
      {/* Верхняя граница ширины обязательна: с `1fr` карточки растягивались на всю
          строку и внутри оставался воздух, а показатели всё равно обрезались —
          выигрывал только пустой фон. Нижняя — предел, за которым три числа с
          подписями наезжают друг на друга. */}
      <div className="grid grid-cols-1 gap-2
                      sm:grid-cols-[repeat(auto-fill,minmax(208px,244px))] sm:justify-start">
        {children}
      </div>
    </section>
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
  // Тот же порог, что у раскладок: ниже него интерфейс живёт в руке, а не под курсором.
  const narrow = useMaxWidth(1024)
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
  // Планируемые вынимаются из общего потока до раскладки по слоям: иначе они
  // остались бы и внизу, и в «Клиентах и продажах» одновременно.
  const planned = PLANNED_APPS
    .map((code) => all.find((a) => a.code === code))
    .filter((a): a is SsoApp => !!a)
  const isPlanned = (code: string) => PLANNED_APPS.includes(code)

  const management = all.filter((a) => a.layer === 'admin' && !COMMERCE_APPS.includes(a.code))
  const services = all.filter((a) => a.layer === 'service' && !COMMERCE_APPS.includes(a.code))
  const apps = all.filter((a) => !isPlanned(a.code) && (COMMERCE_APPS.includes(a.code)
    || (a.layer !== 'admin' && a.layer !== 'service')))
  // Два контура приложений: обращённый к клиенту (продать, обслужить) и внутренний
  // (построить, содержать, посчитать).
  const lead = apps.filter((a) => LEAD_APPS.includes(a.code))
  // Порядок рабочей строки задан явно, а не порядком реестра: он отражает,
  // в каком порядке к продуктам обращаются в течение дня.
  const commerce = COMMERCE_APPS
    .map((code) => apps.find((a) => a.code === code))
    .filter((a): a is SsoApp => !!a)
  // Учётная строка: содержание сети и деньги за неё — в том порядке, в каком
  // цифра идёт от объекта к отчётности.
  const INTERNAL_ORDER = ['ops', 'finance', 'accounting']
  const internal = apps
    .filter((a) => !COMMERCE_APPS.includes(a.code) && !LEAD_APPS.includes(a.code))
    .sort((a, b) => {
      const ia = INTERNAL_ORDER.indexOf(a.code), ib = INTERNAL_ORDER.indexOf(b.code)
      // Незаданные продукты идут следом за перечисленными, порядком реестра.
      return (ia < 0 ? INTERNAL_ORDER.length : ia) - (ib < 0 ? INTERNAL_ORDER.length : ib)
    })

  /**
   * Открыть продукт. На десктопе рабочее место уходит в НОВУЮ вкладку (решение МАГа
   * 27.07.2026): стол остаётся открытым, продукты копятся вкладками рядом. Сервисы с
   * кнопкой в шапке (Чат) открываются здесь же — они часть текущего экрана.
   *
   * На телефоне — в ТЕКУЩЕЙ вкладке. Держать рабочие места параллельно там не выходит:
   * переключение между вкладками стоит двух жестов через меню браузера, вкладки копятся
   * и теряются, а «назад» перестаёт работать. Плюс новая вкладка открывается со своими
   * настройками — в режиме эмуляции устройства она приходит уже в десктопном виде.
   */
  async function openProduct(app: SsoApp) {
    if (app.mode === 'internal' && app.route) {
      // В текущей вкладке: телефон, продукты с кнопкой рядом (Чат · Заявки ·
      // Конференция) и функции Ядра — «Инфо», «Данные», «Управление», «Пульс».
      // Последние не рабочие места продуктов, а экраны самого пространства.
      if (narrow || hasSideButton(app.code) || isCoreApp(app.code)) {
        navigate(app.route)
        onNavigate?.()
      }
      else {
        window.open(`${window.location.origin}${BASE}${app.route}`, '_blank', 'noopener,noreferrer')
        onNavigate?.()
      }
      return
    }
    await openExternal(app)
  }

  /** Открыть внешнее приложение: SSO — по handoff-токену, мост — ссылкой.
   *  Новая вкладка только на десктопе (см. openProduct); чужой домен уходит в неё
   *  всегда — там своя сессия и свой «назад», это решает сам хук. */
  async function openExternal(app: SsoApp) {
    await openViaHook(app.code, !narrow)
  }

  /** Плитка любого продукта пространства: подпись говорит, ЧТО за ним стоит, а не как он
   *  откроется. Способ входа виден значком «вход отдельный» в углу, а пока подпись занимала
   *  «Открывается по ссылке», описание из реестра не доходило до человека вовсе — и
   *  «Конференции» молчали о том, что вход без регистрации, прямо в браузере. */
  function ProductTile({ a }: { a: SsoApp }) {
    const subtitle = a.description
      || (a.mode === 'internal' ? 'Продукт пространства'
        : a.mode === 'link' ? 'Открывается по ссылке' : 'Единый вход')
    return (
      <Tile
        title={a.name}
        subtitle={subtitle}
        icon={ICONS[a.icon] ?? LayoutGrid}
        badge={a.mode === 'link' ? 'вход отдельный' : undefined}
        busy={busy === a.code}
        readiness={productReadiness(a.code, company.profileId)}
        onClick={() => openProduct(a)}
      />
    )
  }

  /** Слои продуктов — общая часть стола и встроенной панели «Приложения». */
  function Layers() {
    return (
      <>
        {lead.length > 0 && (
          <Section title="Руководство" hint="как идут дела и куда вмешаться">
            {lead.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}
        {commerce.length > 0 && (
          <Section title="Клиенты и продажи" hint="кому продаём и как обслуживаем" divider={lead.length > 0}>
            {commerce.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}
        <Section title="Сеть и учёт" hint="чем владеем и как считаем" divider>
          {internal.map((a) => <ProductTile key={a.code} a={a} />)}
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
        {services.length > 0 && (
          <Section title="Сервисы экосистемы" hint="общие для всех приложений" divider>
            {services.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}
        {management.length > 0 && (
          <Section title="Ядро системы" divider>
            {management.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}
        {planned.length > 0 && (
          <Section title="Планы" hint="заведены, но ещё не работают" divider>
            {planned.map((a) => <ProductTile key={a.code} a={a} />)}
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
        <Layers />
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
          <span className="hidden rounded-xl bg-primary/10 p-2 text-primary sm:inline-flex">
            <LayoutGrid className="size-5" />
          </span>
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

        {/* Все слои — из ОДНОГО каталога продуктов пространства (`Layers`), тем же
            составом, что и панель «Приложения» в рабочей области приложений. */}
        <Layers />
      </MobileShell>

      {/* Окно «Взаимодействие» — то же, что открывают кнопки шапки в приложениях.
          Стол живёт вне AdminLayout, который его монтирует, и без этой строки
          кнопки Чат/Задачи/Инфо переключали состояние вхолостую: подсвечивались,
          но рисовать окно было некому. Док сюда не берём — рейла на столе нет. */}
      <InteractionModal />
    </div>
  )
}
