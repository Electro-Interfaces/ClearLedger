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
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  LayoutGrid, ExternalLink, Loader2, LogOut,
  LifeBuoy, ClipboardList, Video, FileText, MessagesSquare,
  ShieldCheck, BookOpen, HardHat, Gauge, BarChart3, Wallet, Database, MessageCircle,
  Building2, ShoppingCart, Megaphone,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CompanySelector } from '@/components/company/CompanySelector'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { listSsoApps, authorizeApp, hasSideButton, type SsoApp } from '@/services/ssoService'

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
  // Продукты разреза Учёта (config/spaceProducts.ts).
  'hard-hat': HardHat,
  'gauge': Gauge,
  'bar-chart-3': BarChart3,
  'wallet': Wallet,
  'database': Database,
  'building-2': Building2,
  'shopping-cart': ShoppingCart,
  'megaphone': Megaphone,
}

interface TileProps {
  title: string
  subtitle: string
  icon: typeof FileText
  badge?: string
  busy?: boolean
  onClick: () => void
}

/**
 * Плитка продукта — строка, а не карточка: иконка, название и одна строка пояснения.
 * Прежняя карточка занимала 170 px ради двух строк текста, поэтому уже на десяти
 * продуктах стол уезжал в прокрутку. Пространство растёт — плитка обязана быть плотной.
 */
function Tile({ title, subtitle, icon: Icon, badge, busy, onClick }: TileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      title={badge ? `${title} — ${badge}` : title}
      className="group flex items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5 text-left
                 transition-colors duration-200 hover:border-primary/50 hover:bg-accent/40 disabled:opacity-60"
    >
      <span className="shrink-0 rounded-lg bg-primary/10 p-2 text-primary transition-colors group-hover:bg-primary group-hover:text-white">
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium leading-tight">{title}</span>
        <span className="block truncate text-xs text-muted-foreground">{subtitle}</span>
      </span>
      {/* Свой вход — значком, а не подписью: он важен при первом знакомстве, а места
          в строке занимает как буква. Расшифровка — во всплывающей подсказке. */}
      {badge && <ExternalLink className="size-3.5 shrink-0 text-muted-foreground" />}
    </button>
  )
}

/**
 * Слой стола: подпись слева, плитки справа. Заголовок отдельной строкой стоил трёх
 * строк высоты на каждый слой — при трёх слоях это уже экран. Сетка `auto-fill` сама
 * набирает столько колонок, сколько влезает, поэтому широкий экран показывает слой
 * одной строкой, а узкий — переносит.
 */
function Section({ title, hint, children, grow }: {
  title: string; hint?: string; children: React.ReactNode; grow?: boolean
}) {
  return (
    <section className={`grid gap-x-4 gap-y-2 md:grid-cols-[132px_1fr] ${grow ? 'min-h-0' : ''}`}>
      <div className="md:pt-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">{title}</h2>
        {hint && <p className="mt-0.5 hidden text-[11px] text-muted-foreground/50 md:block">{hint}</p>}
      </div>
      {/* Прокрутка достаётся только слою, который может вырасти (приложения), и только
          когда он действительно не помещается: шапка и остальные слои остаются на месте. */}
      <div className={`grid grid-cols-[repeat(auto-fill,minmax(216px,1fr))] gap-2 ${grow ? 'min-h-0 overflow-y-auto pr-1' : ''}`}>
        {children}
      </div>
    </section>
  )
}

export function EcosystemHomePage() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { company, companyId, companies } = useCompany()
  const [busy, setBusy] = useState<string | null>(null)

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
  const management = all.filter((a) => a.layer === 'admin')
  const services = all.filter((a) => a.layer === 'service')
  const apps = all.filter((a) => a.layer !== 'service' && a.layer !== 'admin')

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

  /** Открыть внешнее приложение: SSO — по handoff-токену, мост — просто ссылкой. */
  async function openExternal(app: SsoApp) {
    if (busy) return
    setBusy(app.code)
    try {
      const url = await authorizeApp(app.code, companyId)
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Единый вход не настроен' : 'Не удалось открыть приложение')
    } finally {
      setBusy(null)
    }
  }

  /** Плитка любого продукта пространства: подпись объясняет, как он откроется. */
  function ProductTile({ a }: { a: SsoApp }) {
    const subtitle = a.mode === 'internal'
      ? (a.description || 'Продукт пространства')
      : a.mode === 'link' ? 'Открывается по ссылке' : 'Единый вход'
    return (
      <Tile
        title={a.name}
        subtitle={subtitle}
        icon={ICONS[a.icon] ?? LayoutGrid}
        badge={a.mode === 'link' ? 'вход отдельный' : undefined}
        busy={busy === a.code}
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
          <div className="min-w-0">
            {/* После входа человек внутри своего пространства: в шапке только имя
                компании, без имени платформы и слова «экосистема». */}
            <div className="truncate font-semibold leading-tight">{company.name}</div>
            <div className="truncate text-xs text-muted-foreground">Рабочее пространство</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
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
      <main className="mx-auto flex w-full min-h-0 max-w-[1600px] flex-1 flex-col gap-5 px-4 py-5 sm:px-8">
        {/* Приветствие — одна строка: компания уже названа в шапке, повторять её
            отдельным абзацем значит занять высоту ради того же слова. */}
        <h1 className="shrink-0 text-lg font-semibold">
          {user?.name ? `Здравствуйте, ${user.name}` : 'Рабочий стол'}
        </h1>

        {/* Все три слоя — из ОДНОГО каталога продуктов пространства. Раньше Управление,
            Учёт и Чаты рисовались хардкодом, и в списке приложений их не было: состав
            стола расходился с реестром. Теперь источник один. */}
        {management.length > 0 && (
          <Section title="Управление">
            {management.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}

        {services.length > 0 && (
          <Section title="Сервисы экосистемы" hint="общие для всех приложений">
            {services.map((a) => <ProductTile key={a.code} a={a} />)}
          </Section>
        )}

        {/* Слой приложений растёт вместе с пространством — прокрутка достаётся ему. */}
        <Section title="Приложения" grow>
          {apps.map((a) => <ProductTile key={a.code} a={a} />)}
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
