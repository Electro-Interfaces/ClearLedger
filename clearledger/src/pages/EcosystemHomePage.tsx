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
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutGrid, ExternalLink, Loader2, LogOut,
  LifeBuoy, ClipboardList, Video, FileText, MessagesSquare,
  ShieldCheck, BookOpen, HardHat, Gauge, BarChart3, Wallet, Database, MessageCircle,
  Building2, ShoppingCart, Megaphone, Network, Calculator, Stethoscope, Activity,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CompanySelector } from '@/components/company/CompanySelector'
import { HeaderInteractionButtons } from '@/components/layout/HeaderInteractionButtons'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { listSsoApps, hasSideButton, type SsoApp } from '@/services/ssoService'
import { useOpenApp } from '@/hooks/useOpenApp'
import { READINESS_LABEL, productReadiness, type Readiness } from '@/config/spaceProducts'
import { getDeskSummary, type DeskMetric } from '@/services/spaceDeskService'

/** База сборки SPA (`/ClearLedger/`) — новая вкладка открывается по полному адресу. */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

/** Иконка по имени из реестра Ядра (`eco_apps.icon`, манифест `apps/<code>.yml`).
 *  Неизвестное имя — LayoutGrid: плитка появляется, просто без своего значка. */
const ICONS: Record<string, typeof FileText> = {
  'life-buoy': LifeBuoy,
  'clipboard-list': ClipboardList,
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
}

interface TileProps {
  title: string
  subtitle: string
  icon: typeof FileText
  badge?: string
  busy?: boolean
  readiness?: Readiness
  metrics?: DeskMetric[]
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
// «Поддержка» — сервис экосистемы, а не коммерческое приложение (решение МАГа
// 31.07.2026): заявки и обслуживание общие для всех продуктов, как чат.
const COMMERCE_APPS = ['sales', 'shop', 'corp', 'marketing', 'monitor', 'processing']
// «Пульс» — рабочее место руководителя над ВСЕМ пространством, поэтому своя строка
// вверху стола, а не «чем владеем и как считаем» (ecosystem-deploy/docs/PULSE.md).
// Круг узкий: у кого права нет, тот этой строки не увидит вовсе.
const LEAD_APPS = ['pulse']

/** Тон показателя: цветом выделяем только то, что требует внимания или радует. */
const TONE_CLASS: Record<string, string> = {
  ok: 'text-emerald-500',
  warn: 'text-amber-500',
  bad: 'text-red-500',
}

/**
 * Карточка продукта: имя, точка готовности и два-три показателя его контура.
 *
 * Плитка была строкой с названием — стол отвечал только «куда войти». Администратору
 * нужен и второй ответ: что за плиткой живёт. Поэтому под именем идут цифры из самого
 * продукта (люди, объекты, сессии, заявки, свежесть данных) — по ним видно, где работа
 * идёт, а где пусто, не заходя внутрь.
 *
 * Описание из реестра длинное («Стройка сети: подбор площадок, портфель проектов…») и в
 * карточку не помещается — оно осталось в подсказке; строку заняли показатели, потому
 * что их читают каждый день, а описание один раз.
 *
 * Показателей нет (мост, пустой продукт) — карточка честно остаётся без цифр: место
 * держит подпись состояния, а не выдуманный ноль.
 *
 * На телефоне плитка складывается в ОДНУ строку: имя слева, показатели справа тем же
 * рядом. Двухэтажная карточка занимала 99 px, и до нижних продуктов приходилось
 * листать три экрана — на десктопе стол помещается целиком, а на телефоне терял это
 * свойство. Цель нажатия остаётся во всю ширину строки.
 */
function Tile({ title, subtitle, icon: Icon, badge, busy, readiness, metrics, onClick }: TileProps) {
  const shown = (metrics ?? []).slice(0, 3)
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      title={[title, subtitle, badge, readiness && READINESS_LABEL[readiness]]
        .filter(Boolean).join(' · ')}
      className="group relative flex min-h-12 items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2 text-left
                 transition-colors duration-200 hover:border-primary/50 hover:bg-accent/40 disabled:opacity-60
                 sm:min-h-0 sm:flex-col sm:items-stretch sm:gap-2 sm:py-2.5"
    >
      {/* Готовность продукта — точка в углу. Расшифровка в подсказке плитки: цвет
          читается с одного взгляда, слова нужны только при первом знакомстве. */}
      {readiness && (
        <span aria-hidden="true"
          className={`absolute right-2 top-1/2 size-2 -translate-y-1/2 rounded-full sm:top-2 sm:translate-y-0 ${DOT_CLASS[readiness]}`} />
      )}
      {/* Имя продукта — приоритет строки: место сначала ему, показатели ужимаются
          вокруг. Иначе на трёх метриках «Пульс» превращался в «Г». */}
      <span className="flex min-w-0 flex-1 items-center gap-2.5 sm:w-full sm:flex-none">
        <span className="shrink-0 rounded-lg bg-primary/10 p-1.5 text-primary transition-colors group-hover:bg-primary group-hover:text-white">
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium leading-snug sm:pr-3 sm:whitespace-normal">{title}</span>
        {/* Свой вход — значком, а не подписью: важен при первом знакомстве, а места
            в строке занимает как буква. Расшифровка — в подсказке всей плитки. */}
        {badge && <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />}
      </span>
      {shown.length > 0 ? (
        <span className="flex shrink-0 items-baseline gap-2.5 pr-4
                         sm:items-end sm:gap-3 sm:border-t sm:border-border/60 sm:pr-0 sm:pt-1.5">
          {shown.map((m, i) => (
            /* В строку телефона помещается один показатель — главный. Остальные
               живут на десктопе, где у плитки своя строка под цифры. */
            <span key={m.label}
              className={`items-baseline gap-1 sm:flex sm:min-w-0 sm:flex-1 sm:gap-0 ${i === 0 ? 'flex' : 'hidden'}`}>
              <span className={`whitespace-nowrap text-[13px] font-semibold leading-tight tabular-nums sm:block sm:truncate
                                ${m.tone ? TONE_CLASS[m.tone] ?? '' : ''}`}>
                {m.value}
              </span>
              <span className="whitespace-nowrap text-[11px] leading-tight text-muted-foreground/70 sm:block sm:truncate sm:text-[10px]">
                {m.label}
              </span>
            </span>
          ))}
        </span>
      ) : (
        /* Без показателей место держит описание — но только на десктопе. В строке
           телефона оно вытесняло имя продукта, а обрезок «Чем пространство связано
           с в…» не сообщает ничего: полный текст и так лежит в подсказке плитки. */
        <span className="hidden text-[10px] leading-tight text-muted-foreground/60
                         sm:block sm:border-t sm:border-border/60 sm:pt-1.5">
          {subtitle}
        </span>
      )}
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
    <section className={`grid gap-x-4 gap-y-2 md:grid-cols-[132px_1fr]
                         ${divider ? 'border-t border-border/60 pt-4' : ''}`}>
      <div className="md:pt-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">{title}</h2>
        {hint && <p className="mt-0.5 hidden text-[11px] text-muted-foreground/50 md:block">{hint}</p>}
      </div>
      {/* Колонка чуть шире прежней: в карточке теперь строка показателей, и на 200 px
          три числа с подписями наезжали друг на друга. */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] gap-2">
        {children}
      </div>
    </section>
  )
}

export function EcosystemHomePage() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { company, companyId, companies } = useCompany()
  // Открытие продуктов — общей логикой с лаунчером: там же живёт особый случай
  // «Конференций», где вместо перехода на чужую главную создаётся комната.
  const { open: openViaHook, busy } = useOpenApp()

  const q = useQuery({
    queryKey: ['sso-apps', companyId],
    queryFn: () => listSsoApps(companyId),
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  // Показатели продуктов — отдельным запросом: каталог плиток приходит первым и стол
  // рисуется сразу, цифры доезжают следом (все они COUNT'ы, но ждать их незачем).
  const desk = useQuery({
    queryKey: ['desk-summary', companyId],
    queryFn: () => getDeskSummary(companyId),
    enabled: isApiEnabled() && !!companyId,
    staleTime: 60_000,
  })
  // RBAC-гейт стола: allowed_apps — коды, доступных ролью в компании (null = не ограничено,
  // напр. админ). Бэкенд уже отфильтровал apps; здесь гейтим внутренние плитки Ledger и Чат.
  const allowed = q.data?.allowed_apps ?? null
  const canOpen = (code: string) => allowed === null || allowed.includes(code)
  const all: SsoApp[] = (q.data?.apps ?? []).filter((a) => canOpen(a.code))
  const management = all.filter((a) => a.layer === 'admin')
  const services = all.filter((a) => a.layer === 'service')
  const apps = all.filter((a) => a.layer !== 'service' && a.layer !== 'admin')
  // Два контура приложений: обращённый к клиенту (продать, обслужить) и внутренний
  // (построить, содержать, посчитать). Порядок внутри — из реестра, как и был.
  const lead = apps.filter((a) => LEAD_APPS.includes(a.code))
  const commerce = apps.filter((a) => COMMERCE_APPS.includes(a.code))
  const internal = apps.filter(
    (a) => !COMMERCE_APPS.includes(a.code) && !LEAD_APPS.includes(a.code))

  /**
   * Открыть продукт. Рабочее место уходит в НОВУЮ вкладку (решение МАГа 27.07.2026):
   * стол остаётся открытым, продукты копятся вкладками рядом. Сервисы с кнопкой в шапке
   * (Чат) открываются здесь же — они часть текущего экрана, а не отдельное место.
   */
  async function openProduct(app: SsoApp) {
    if (app.mode === 'internal' && app.route) {
      if (hasSideButton(app.code)) navigate(app.route)
      else window.open(`${window.location.origin}${BASE}${app.route}`, '_blank', 'noopener,noreferrer')
      return
    }
    await openExternal(app)
  }

  /** Открыть внешнее приложение: SSO — по handoff-токену, мост — ссылкой. */
  async function openExternal(app: SsoApp) {
    await openViaHook(app.code, true)
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
        metrics={desk.data?.products[a.code]?.metrics}
        onClick={() => openProduct(a)}
      />
    )
  }

  return (
    // Стол занимает ровно экран и сам не прокручивается: это витрина пространства,
    // а не документ. Прокрутку получает только слой приложений, если продуктов станет
    // больше, чем помещается (docs/SPACE.md §1 — состав приложений открыт).
    <div className="flex h-dvh flex-col overflow-hidden bg-background">
      <header className="flex h-header shrink-0 items-center justify-between gap-4 border-b border-border px-4 sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <span className="rounded-xl bg-primary/10 p-2 text-primary">
            <LayoutGrid className="size-5" />
          </span>
          {/* После входа человек внутри своего пространства: в шапке только имя
              компании, без имени платформы и слова «экосистема». На телефоне имя
              скрыто — оно ничего не сообщает тому, кто и так внутри, а строка
              нужнее под связь с пространством (решение МАГа 01.08.2026). */}
          <div className="hidden min-w-0 sm:block">
            <div className="truncate font-semibold leading-tight">{company.name}</div>
            <div className="truncate text-xs text-muted-foreground">Рабочее пространство</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 sm:gap-3">
          {/* Чат · Заявки · Конференция — тот же блок, что в шапке приложений:
              связь с пространством лежит на одном месте, куда бы человек ни зашёл. */}
          <HeaderInteractionButtons conference />
          {companies.length > 1 && <CompanySelector />}
          <Button variant="ghost" size="sm" onClick={logout} title="Выйти">
            <LogOut className="size-4" />
            <span className="ml-2 hidden sm:inline">Выйти</span>
          </Button>
        </div>
      </header>

      {/* Ширину не режем до 1024: на широком экране это выталкивало продукты вниз
          при пустых полях по бокам. Предел нужен лишь чтобы строка плиток не
          растягивалась бесконечно на панорамных мониторах. */}
      {/* Прокручивается вся область стола, а не один слой: слоёв четыре, продуктов
          двенадцать и число их растёт — при нехватке высоты верхние слои иначе просто
          обрезаются, и добраться до них нечем. Шапка остаётся на месте. */}
      <main className="mx-auto flex w-full min-h-0 max-w-[1600px] flex-1 flex-col gap-5 overflow-y-auto px-4 py-5 sm:px-8">
        {/* Приветствие — одна строка: компания уже названа в шапке, повторять её
            отдельным абзацем значит занять высоту ради того же слова. */}
        <h1 className="shrink-0 text-lg font-semibold">
          {user?.name ? `Здравствуйте, ${user.name}` : 'Рабочий стол'}
        </h1>

        {/* Все три слоя — из ОДНОГО каталога продуктов пространства. Раньше Управление,
            Учёт и Чаты рисовались хардкодом, и в списке приложений их не было: состав
            стола расходился с реестром. Теперь источник один. */}
        {/* Руководителю его рабочее место нужно первым — он заходит за состоянием
            дел, а не за настройкой пространства. */}
        {lead.length > 0 && (
          <Section title="Руководство" hint="как идут дела и куда вмешаться">
            {lead.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}

        {management.length > 0 && (
          <Section title="Ядро системы" divider={lead.length > 0}>
            {management.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}

        {services.length > 0 && (
          <Section title="Сервисы экосистемы" hint="общие для всех приложений" divider>
            {services.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}

        {/* Приложения разведены по двум контурам (решение МАГа 28.07.2026): клиентская
            сторона и внутренняя. Один список из десяти плиток не читался — рядом
            стояли «Продажи» и «Бухгалтерия», между которыми нет ничего общего. */}
        {commerce.length > 0 && (
          <Section title="Клиенты и продажи" hint="кому продаём и как обслуживаем" divider>
            {commerce.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}

        {/* Второй контур растёт вместе с пространством — прокрутка достаётся ему. */}
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
      </main>
    </div>
  )
}
