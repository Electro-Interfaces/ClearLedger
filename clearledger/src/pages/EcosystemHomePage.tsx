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
import { toast } from 'sonner'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutGrid, Rows3, ExternalLink, Loader2, Network, FileText, Star, ChevronDown,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { HeaderUserMenu } from '@/components/layout/HeaderUserMenu'
import { MobileContextBar } from '@/components/layout/MobileContextBar'
import { MobileShell } from '@/components/common/MobileShell'
import { MobileBottomNav } from '@/components/layout/MobileBottomNav'
import { HeaderInteractionButtons } from '@/components/layout/HeaderInteractionButtons'
import { CompanySelector } from '@/components/company/CompanySelector'
import { ECOSYSTEM_BRAND } from '@/config/brand'
import { InteractionModal } from '@/components/support/InteractionModal'
import { SidebarNavContent } from '@/components/layout/AppSidebar'
import { SidebarProvider } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { type SsoApp } from '@/services/ssoService'
import { listPartnerSpaces, visitPartnerSpace } from '@/services/partnerSpaceService'
import { useOpenApp } from '@/hooks/useOpenApp'
import { assignTop, inFrame, spaceUrl } from '@/lib/topNav'
import { useTouchInput } from '@/hooks/use-mobile'
import { useFavoriteApps } from '@/hooks/useFavoriteApps'
import { readSectionOpen } from '@/hooks/useSectionOpen'
import { useSpaceApps } from '@/hooks/useSpaceApps'
import { appIcon } from '@/config/spaceLauncher'
import {
  READINESS_LABEL, SPACE_PRODUCTS, productReadiness, type Readiness,
} from '@/config/spaceProducts'


/**
 * Вид стола: плитки или строки (просьба МАГа 05.09.2026). Состав, порядок и разбивка
 * по строкам одни и те же — меняется только подача: плитка показывает продукт с
 * пояснением, строка вмещает вдвое больше продуктов на экран и читается списком.
 *
 * Выбор помнится между заходами: это привычка человека, а не настройка пространства,
 * поэтому живёт в браузере, а не в профиле.
 *
 * Под пальцем выбора нет — только список (решение МАГа 06.09.2026): плитка на узком
 * экране умещает в ряд одну-две штуки, и каталог растягивается на несколько экранов.
 * Список показывает всё сверху вниз одним жестом, которым человек и так листает.
 */
export type LauncherView = 'tiles' | 'list'
const VIEW_KEY = 'space.launcher.view'

// Свёрнута строка или раскрыта — общее состояние с меню в рельсе (`useSectionOpen`).

function readView(): LauncherView {
  try {
    return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'tiles'
  } catch {
    return 'tiles'   // приватное окно или запрет на хранилище — вид по умолчанию
  }
}

function ViewSwitch({ value, onChange }: {
  value: LauncherView; onChange: (v: LauncherView) => void
}) {
  const item = (v: LauncherView, Icon: typeof FileText, label: string) => (
    <button
      type="button"
      onClick={() => onChange(v)}
      aria-pressed={value === v}
      title={label}
      className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors
                 ${value === v
                   ? 'bg-primary text-primary-foreground'
                   : 'text-muted-foreground hover:bg-accent hover:text-foreground'}`}
    >
      <Icon className="size-4" />
      <span className="hidden sm:inline">{label}</span>
    </button>
  )
  return (
    <div role="group" aria-label="Вид списка приложений"
      className="flex shrink-0 items-center gap-1 rounded-xl border border-border/70 bg-card/50 p-1">
      {item('tiles', LayoutGrid, 'Карточки')}
      {item('list', Rows3, 'Список')}
    </div>
  )
}

/**
 * Звёздочка «избранное» — РЯДОМ с плиткой, а не внутри её кнопки: вложенная кнопка
 * невалидна в разметке, и клавиатура с экранным диктором до неё не доходят.
 */
function FavoriteStar({ active, title, onToggle, className }: {
  active: boolean; title: string; onToggle: () => void; className?: string
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={active}
      aria-label={`${title}: ${active ? 'убрать из избранного' : 'в избранное'}`}
      title={active ? 'Убрать из избранного' : 'В избранное'}
      className={`flex size-9 shrink-0 items-center justify-center rounded-lg transition-colors
                  hover:bg-accent hover:text-amber-400 sm:size-8
                  ${active ? 'text-amber-400' : 'text-muted-foreground/45'} ${className ?? ''}`}
    >
      <Star className={`size-4 ${active ? 'fill-current' : ''}`} />
    </button>
  )
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
  /** Отмечено ли приложение избранным (звёздочка справа). */
  favorite?: boolean
  /** Переключить избранное. Не передан — звёздочки нет (стенд показа, пространства клиентов). */
  onToggleFavorite?: () => void
}

/** Точка готовности: зелёная — рабочий, жёлтая — в развитии, красная — в подключении. */
const DOT_CLASS: Record<Readiness, string> = {
  ready: 'bg-emerald-500',
  partial: 'bg-amber-400',
  draft: 'bg-red-500',
}

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
  favorite, onToggleFavorite,
}: TileProps) {
  return (
    <div className="relative h-full">
    <button
      type="button"
      onClick={onClick}
      disabled={busy || inactive}
      title={[title, availability, subtitle, badge, readiness && READINESS_LABEL[readiness]]
        .filter(Boolean).join(' · ')}
      className={`group relative flex h-full min-h-12 items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left
                  transition-colors duration-200 sm:min-h-0 sm:flex-col sm:items-stretch sm:gap-2
                  ${inactive
                    ? 'cursor-inherit border-dashed border-border bg-card'
                    : 'border-primary/30 bg-primary/[0.08] hover:border-primary/50 hover:bg-primary/[0.14]'}
                  ${busy ? 'opacity-60' : ''}`}
    >
      {/* Имя продукта. Готовность — точка в конце строки, а не абсолютом в углу:
          в потоке она занимает своё место и не наезжает на длинное название. */}
      <span className={`flex min-w-0 flex-1 items-center gap-2.5 sm:w-full sm:flex-none
                       ${onToggleFavorite ? 'pr-8' : ''}`}>
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
      {onToggleFavorite && (
        <FavoriteStar active={!!favorite} title={title} onToggle={onToggleFavorite}
          className="absolute right-0.5 top-0.5" />
      )}
    </div>
  )
}

/**
 * Тот же продукт одной строкой — второй вид стола.
 *
 * Строка держит колонки в одном месте по всему столу: значок, имя, готовность,
 * пояснение и способ входа. Поэтому имя — колонка фиксированной ширины, а не
 * «сколько займёт»: иначе пояснения скачут по горизонтали от строки к строке и
 * список перестаёт читаться сверху вниз. На узком экране пояснение уходит —
 * остаётся имя и как продукт открывается.
 */
function Row({
  title, subtitle, icon: Icon, badge, availability, busy, inactive, readiness, onClick,
  favorite, onToggleFavorite,
}: TileProps) {
  return (
    <div className="flex min-w-0 items-center gap-1">
    <button
      type="button"
      onClick={onClick}
      disabled={busy || inactive}
      title={[title, availability, subtitle, badge, readiness && READINESS_LABEL[readiness]]
        .filter(Boolean).join(' · ')}
      className={`group flex min-w-0 flex-1 items-center gap-3 rounded-lg border px-3 py-2.5 text-left
                  transition-colors duration-200
                  ${inactive
                    ? 'cursor-inherit border-dashed border-border bg-card'
                    : 'border-border/70 bg-card/40 hover:border-primary/50 hover:bg-primary/[0.10]'}
                  ${busy ? 'opacity-60' : ''}`}
    >
      <span className={`shrink-0 rounded-md p-1.5 transition-colors
                       ${inactive
                         ? 'bg-muted text-muted-foreground'
                         : 'bg-primary/15 text-primary group-hover:bg-primary group-hover:text-primary-foreground'}`}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
      </span>
      <span className="flex min-w-0 shrink-0 items-center gap-2 sm:w-56">
        <span className="min-w-0 truncate text-sm font-medium leading-snug">{title}</span>
        {readiness && (
          <span aria-hidden="true"
            className={`size-2 shrink-0 rounded-full ${DOT_CLASS[readiness]}`} />
        )}
      </span>
      <span className="hidden min-w-0 flex-1 truncate text-xs text-muted-foreground/90 sm:inline">
        {subtitle}
      </span>
      {badge && <ExternalLink className="ml-auto size-3.5 shrink-0 text-muted-foreground sm:ml-0" />}
      {availability && (
        <span className={`ml-auto shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-medium
                         ${inactive
                           ? 'border border-dashed border-border bg-card text-muted-foreground'
                           : 'bg-primary text-primary-foreground'}`}>
          {availability}
        </span>
      )}
    </button>
      {onToggleFavorite && (
        <FavoriteStar active={!!favorite} title={title} onToggle={onToggleFavorite} />
      )}
    </div>
  )
}

/**
 * Слой стола: подпись слева, плитки справа. Заголовок отдельной строкой стоил трёх
 * строк высоты на каждый слой — при трёх слоях это уже экран.
 *
 * Плитки ПЕРЕНОСЯТСЯ на столько строк, сколько нужно (решение МАГа 06.09.2026).
 * Раньше слой ехал одной строкой с горизонтальной прокруткой: в «Системных»
 * половина приложений пряталась за краем экрана — о ней надо было догадаться, —
 * а при перетаскивании соседние карточки наезжали друг на друга. Высоту стол
 * никак не ограничивает: он и так прокручивается сверху вниз.
 */
function Section({
  title, hint, children, divider, view = 'tiles', collapsible, storageKey,
  count, defaultOpen = false,
}: {
  title: string; hint?: string; children: React.ReactNode
  /** Линия сверху — граница уровня стола (Ядро · Сервисы · Приложения). */
  divider?: boolean
  /** Плитки строкой с прокруткой или список сверху вниз. */
  view?: LauncherView
  /** Строку можно свернуть. Свёрнутая строка по умолчанию — решение МАГа 06.09.2026. */
  collapsible?: boolean
  /** Ключ, под которым помнится «открыта или закрыта». */
  storageKey?: string
  /** Сколько приложений внутри — видно в свёрнутом заголовке. */
  count?: number
  /** Открыта ли строка, пока человек сам её не открывал и не закрывал. */
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(() => (collapsible ? readSectionOpen(storageKey ?? title, defaultOpen) : true))
  function toggle() {
    const next = !open
    setOpen(next)
    try { localStorage.setItem(`space.launcher.open.${storageKey ?? title}`, next ? '1' : '0') } catch { /* хранилище недоступно */ }
  }
  return (
    <section className={`grid min-w-0 gap-x-4 gap-y-2 md:grid-cols-[116px_minmax(0,1fr)]
                         ${divider ? 'border-t border-border/60 pt-4' : ''}`}>
      <div className="md:pt-2">
        {collapsible ? (
          // Заголовок сам открывает строку: отдельная кнопка-стрелка рядом с
          // подписью — вторая цель на телефоне там, где хватает одной.
          <button type="button" onClick={toggle} aria-expanded={open}
            className="flex min-h-9 w-full items-center gap-1.5 text-left text-[11px] font-semibold
                       uppercase tracking-widest text-muted-foreground/60 transition-colors
                       hover:text-foreground">
            <ChevronDown className={`size-3.5 shrink-0 transition-transform ${open ? '' : '-rotate-90'}`} />
            {title}
            {/* Число рядом с подписью: у свёрнутой строки это единственный признак,
                что внутри что-то есть и стоит её открыть. */}
            {typeof count === 'number' && count > 0 && (
              <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium
                               tabular-nums text-muted-foreground/80">
                {count}
              </span>
            )}
          </button>
        ) : (
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">{title}</h2>
        )}
        {hint && <p className="mt-0.5 hidden text-[11px] text-muted-foreground/50 md:block">{hint}</p>}
      </div>
      {open && (
      <div
        role="region"
        aria-label={`${title}: приложения`}
        className={view === 'list'
          ? 'flex min-w-0 flex-col gap-1 pb-1 pr-1'
          : `grid min-w-0 gap-2 pb-1 pr-1
             grid-cols-[repeat(auto-fill,minmax(min(100%,208px),244px))]`}
      >
        {children}
      </div>
      )}
    </section>
  )
}

/**
 * Оговорка про продукты, которых в пространстве ещё нет.
 *
 * Метки «Открыть здесь» у каждого рабочего продукта больше нет (замечание МАГа
 * 06.09.2026): она стояла на всех плитках подряд и ничего не сообщала — приложение
 * и так открывается нажатием, а кнопка внутри строки заставляла целиться в неё
 * вместо того, чтобы нажать строку. Метка осталась одна и только там, где поведение
 * действительно другое: продукт заведён в реестре, но экрана в этом стеке у него нет.
 *
 * Поэтому и оговорка показывается лишь тогда, когда такие продукты в каталоге есть.
 */
function OptionalAppsLegend() {
  return (
    <div
      className="flex shrink-0 items-center gap-2 rounded-xl border border-border/70 bg-card/50 px-3 py-2.5
                 text-xs text-muted-foreground"
      aria-label="Продукты, которые можно подключить"
    >
      <span className="shrink-0 whitespace-nowrap rounded-full border border-dashed border-border px-2 py-0.5 font-medium text-foreground">
        Отдельное демо
      </span>
      <span>продукт можно подключить к компании, здесь он не открывается</span>
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
  // Вид стола помним между заходами — привычка человека, а не настройка пространства.
  const [storedView, setStoredView] = useState<LauncherView>(readView)
  // Под пальцем вид один — список; выбор и переключатель остаются курсору.
  const touch = useTouchInput()
  const view: LauncherView = touch ? 'list' : storedView
  function changeView(v: LauncherView) {
    setStoredView(v)
    try { localStorage.setItem(VIEW_KEY, v) } catch { /* хранилище недоступно */ }
  }
  const { user } = useAuth()
  const { company } = useCompany()
  // Открытие продуктов — общей логикой с лаунчером: там же живёт особый случай
  // «Конференций», где вместо перехода на чужую главную создаётся комната.
  const { open: openViaHook, busy } = useOpenApp()

  // Каталог продуктов и раскладка строк — общие с меню приложений в левом рельсе
  // (`hooks/useSpaceApps`): второго списка приложений в пространстве нет.
  const { apps: all, sections, isLoading } = useSpaceApps()

  /**
   * Избранное человека (просьба МАГа 06.09.2026): раздел вверху каталога с тем, чем
   * он пользуется чаще всего, — отмечается звёздочкой прямо в строке.
   *
   * Список тот же, что «Закреплённые приложения» в настройке пульта: избранное у
   * человека одно на пространство, поэтому звёздочка в каталоге сразу меняет и блок
   * «Приложения» на пульте. Живёт на сервере, а не в браузере: телефон и рабочий
   * компьютер обязаны показывать одно и то же.
   */
  const { favorites, ready: favReady, toggle: toggleFavorite } = useFavoriteApps()
  // Рабочие продукты (без служебных экранов) — по ним считается «приложения не подключены».
  const productCount = sections
    .filter((x) => x.key !== 'management')
    .reduce((n, x) => n + x.apps.length, 0)
  // Оговорка про «Отдельное демо» нужна только там, где такие продукты в каталоге есть.
  const hasOptional = all.some((a) => a.mode === 'internal' && !a.route)

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
      // Витрина, открытая фреймом в чужом приложении (`public/eco-rail.js`), уводит
      // ВЕРХНЕЕ окно: переход внутри фрейма показал бы продукт в рамке панели.
      if (inFrame()) assignTop(spaceUrl(app.route))
      else navigate(app.route)
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
      assignTop(res.url)
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
    const Item = view === 'list' ? Row : Tile
    return (
      <Item
        key={a.code}
        title={a.name}
        subtitle={subtitle}
        icon={appIcon(a.icon)}
        badge={a.mode === 'link' ? 'вход отдельный' : undefined}
        // Метка — только у продукта, который здесь не открывается. У рабочего её нет:
        // «Открыть здесь» на каждой строке подряд не сообщало ничего.
        availability={isOptional ? 'Отдельное демо' : undefined}
        busy={busy === a.code}
        inactive={isOptional}
        readiness={isOptional ? undefined : productReadiness(a.code, company.profileId)}
        onClick={() => openProduct(a)}
        favorite={favorites.includes(a.code)}
        // Звёздочка появляется, когда избранное вообще прочитано: без ответа сервера
        // нажатие некуда сохранить, а пустая звезда врала бы про «не в избранном».
        onToggleFavorite={favReady && !isOptional ? () => toggleFavorite(a.code) : undefined}
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
        <Section title="Уже внутри" view={view}
                 hint="идёт вместе с пространством — подключать ничего не нужно">
          {included.map(renderProductTile)}
        </Section>
        {later.length > 0 && (
          <Section title="Можно добавить позже" view={view}
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
    // «Учёт» показывается всегда: в этой строке живут сообщения «загрузка» и
    // «приложения не подключены», и без неё стол пустого пространства молчит.
    const visible = sections.filter((x) => x.apps.length > 0 || x.key === 'internal')
    // Избранное — первым слоем и в порядке, в котором человек его набирал.
    const picked = favorites.flatMap((code) => all.filter((a) => a.code === code))
    return (
      <>
        {favReady && (
          <Section title="Избранное" hint="то, чем пользуетесь чаще всего" view={view}>
            {picked.length > 0
              ? picked.map(renderProductTile)
              : (
                // Пустоту объясняем словами, а раздел не прячем: иначе про звёздочку
                // никто не узнает — её негде увидеть до первого нажатия.
                <p className="px-1 py-2 text-sm text-muted-foreground">
                  Отметьте звёздочкой приложения, которыми пользуетесь чаще всего, — они появятся здесь.
                </p>
              )}
          </Section>
        )}
        {/* Под пальцем строки свёрнуты, пока человек их не открыл (решение МАГа
            06.09.2026): на телефоне каталог иначе занимает несколько экранов. На
            десктопе всё раскрыто — там места хватает, и прятать приложения незачем.
            «Учёт» открыт, пока каталог грузится или пуст — там живут сообщения об этом,
            и в свёрнутой строке их не увидеть. */}
        {visible.map((x, idx) => (
          <Section key={x.key} title={x.title} hint={x.hint} view={view}
                   divider={idx > 0 || favReady}
                   collapsible={touch} storageKey={x.key} count={x.apps.length}
                   defaultOpen={x.key === 'internal' && (isLoading || productCount === 0)}>
            {x.apps.map(renderProductTile)}
            {x.key === 'internal' && isLoading && (
              <div className="flex items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Загрузка каталога…
              </div>
            )}
            {x.key === 'internal' && !isLoading && productCount === 0 && (
              <div className="px-3 py-2.5 text-sm text-muted-foreground">
                Приложения не подключены. Состав задаётся в «Управлении» → «Приложения».
              </div>
            )}
          </Section>
        ))}
        {clientSpaces.length > 0 && (
          <Section title="Пространства клиентов" hint="войти своей учётной записью" view={view} divider
                   collapsible={touch} storageKey="client-spaces" count={clientSpaces.length}>
            {clientSpaces.map((c) => {
              const Item = view === 'list' ? Row : Tile
              return (
                <Item
                  key={c.code}
                  title={c.name}
                  subtitle="Рабочее пространство клиента"
                  icon={Network}
                  availability="Войти по пропуску"
                  busy={visiting === c.code}
                  onClick={() => openSpace(c.code)}
                />
              )
            })}
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
        {/* Легенда доступности и вид стола — одной полосой: и то и другое про то,
            КАК читать список приложений, а не про сами приложения. */}
        <div className="flex shrink-0 flex-wrap items-start justify-between gap-3">
          {hasOptional && <OptionalAppsLegend />}
          {!touch && <ViewSwitch value={view} onChange={changeView} />}
        </div>
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
          {/* Бургера здесь нет (решение МАГа 06.09.2026): меню открывает нижняя
              панель — та, до которой достаёт палец. Сама шторка осталась. */}
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
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
                             overflow-y-auto px-4 py-5 max-md:pb-20 sm:px-8">
        {/* Приветствие — одна строка: компания уже названа в шапке, повторять её
            отдельным абзацем значит занять высоту ради того же слова. */}
        <h1 className="shrink-0 text-lg font-semibold">
          {user?.name ? `Здравствуйте, ${user.name}` : 'Рабочий стол'}
        </h1>

        {/* Легенда доступности и вид стола — одной полосой: и то и другое про то,
            КАК читать список приложений, а не про сами приложения. */}
        <div className="flex shrink-0 flex-wrap items-start justify-between gap-3">
          {hasOptional && <OptionalAppsLegend />}
          {!touch && <ViewSwitch value={view} onChange={changeView} />}
        </div>

        {/* Все слои — из ОДНОГО каталога продуктов пространства (`Layers`), тем же
            составом, что и панель «Приложения» в рабочей области приложений. */}
        {renderLayers()}
      </MobileShell>

      {/* Нижняя панель пространства — и на столе: на телефоне она не пропадает нигде
          (решение МАГа 06.09.2026), и меню открывается ею же. */}
      {touch && <MobileBottomNav onMenu={() => setMenuOpen(true)} />}

      {/* Окно «Взаимодействие» — то же, что открывают кнопки шапки в приложениях.
          Стол живёт вне AdminLayout, который его монтирует, и без этой строки
          кнопки Чат/Задачи/Инфо переключали состояние вхолостую: подсвечивались,
          но рисовать окно было некому. Док сюда не берём — рейла на столе нет. */}
      <InteractionModal />
    </div>
  )
}
