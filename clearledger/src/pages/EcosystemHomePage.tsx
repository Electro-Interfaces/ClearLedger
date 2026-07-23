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
  LayoutGrid, ExternalLink, KeyRound, Loader2, ShieldCheck, LogOut,
  LifeBuoy, ClipboardList, Video, FileText, MessagesSquare,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CompanySelector } from '@/components/company/CompanySelector'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { listSsoApps, authorizeApp, type SsoApp } from '@/services/ssoService'

/** Иконка по имени из манифеста (`apps/<code>.yml`, поле icon). */
const ICONS: Record<string, typeof FileText> = {
  'life-buoy': LifeBuoy,
  'clipboard-list': ClipboardList,
  'video': Video,
  'file-text': FileText,
  'messages-square': MessagesSquare,
}

interface TileProps {
  title: string
  subtitle: string
  icon: typeof FileText
  badge?: string
  busy?: boolean
  onClick: () => void
}

function Tile({ title, subtitle, icon: Icon, badge, busy, onClick }: TileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="group flex flex-col items-start gap-3 rounded-2xl border border-border bg-card p-5 text-left
                 transition-all duration-200 hover:border-primary/50 hover:shadow-lg disabled:opacity-60"
    >
      <div className="flex w-full items-start justify-between gap-2">
        <span className="rounded-xl bg-primary/10 p-2.5 text-primary transition-colors group-hover:bg-primary group-hover:text-white">
          {busy ? <Loader2 className="size-5 animate-spin" /> : <Icon className="size-5" />}
        </span>
        {badge && (
          <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
            {badge}
          </span>
        )}
      </div>
      <div className="min-w-0">
        <div className="truncate font-medium">{title}</div>
        <div className="mt-0.5 text-sm text-muted-foreground">{subtitle}</div>
      </div>
    </button>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="mt-8 first:mt-6">
      <div className="flex items-baseline gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {hint && <span className="text-sm text-muted-foreground">{hint}</span>}
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
    </section>
  )
}

export function EcosystemHomePage() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { company, companyId, companies, isCompanyAdmin } = useCompany()
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
  const all: SsoApp[] = q.data?.apps ?? []
  const services = all.filter((a) => a.layer === 'service')
  const apps = all.filter((a) => a.layer !== 'service')
  const chatEnabled = (q.data?.chat_enabled ?? false) && canOpen('chat')
  const canOpenLedger = canOpen('ledger')

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

  function ExternalTile({ a }: { a: SsoApp }) {
    return (
      <Tile
        title={a.name}
        subtitle={a.mode === 'link' ? 'Открывается по ссылке' : 'Единый вход'}
        icon={ICONS[a.icon] ?? LayoutGrid}
        badge={a.mode === 'link' ? 'вход отдельный' : undefined}
        busy={busy === a.code}
        onClick={() => openExternal(a)}
      />
    )
  }

  return (
    <div className="min-h-svh bg-background">
      <header className="flex h-header items-center justify-between gap-4 border-b border-border px-4 sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <span className="rounded-xl bg-primary/10 p-2 text-primary">
            <LayoutGrid className="size-5" />
          </span>
          <div className="min-w-0">
            <div className="truncate font-semibold leading-tight">Экосистема ElsyPlus</div>
            <div className="truncate text-xs text-muted-foreground">{company.name}</div>
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

      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <h1 className="text-2xl font-semibold">
          {user?.name ? `Здравствуйте, ${user.name}` : 'Рабочий стол'}
        </h1>
        <p className="mt-1 text-muted-foreground">{company.name} · Экосистема ElsyPlus</p>

        {/* Слой 1 — Центр управления (админам) */}
        {isCompanyAdmin && (
          <Section title="Центр управления">
            <Tile
              title="Центр управления"
              subtitle="Компании, приложения, пользователи, аудит"
              icon={ShieldCheck}
              onClick={() => navigate('/admin')}
            />
          </Section>
        )}

        {/* Слой 2 — Универсальные сервисы контейнера (чат/заявки/конференции) */}
        {(chatEnabled || services.length > 0) && (
          <Section title="Сервисы экосистемы" hint="общие для всех приложений">
            {chatEnabled && (
              <Tile
                title="Чат"
                subtitle="Переписка в рамках всей экосистемы"
                icon={MessagesSquare}
                onClick={() => navigate('/messages')}
              />
            )}
            {services.map((a) => <ExternalTile key={a.code} a={a} />)}
          </Section>
        )}

        {/* Слой 3 — Приложения экосистемы (Ledger живёт в этом стеке; прочие — SSO/мост) */}
        <Section title="Приложения">
          {canOpenLedger && (
            <Tile
              title="ElsyPlus Ledger"
              subtitle="Учёт, сверка, обмен с 1С"
              icon={FileText}
              onClick={() => navigate('/workspace')}
            />
          )}
          {apps.map((a) => <ExternalTile key={a.code} a={a} />)}
          {q.isLoading && (
            <div className="flex items-center gap-2 p-5 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Загрузка каталога…
            </div>
          )}
        </Section>

        {/* Легенда: почему часть приложений просит свой вход (Фаза 0 — мосты). */}
        {all.some((a) => a.mode === 'link') && (
          <p className="mt-8 flex items-center gap-2 text-xs text-muted-foreground">
            <ExternalLink className="size-3.5" />
            «Вход отдельный» — сервис пока живёт на своём домене и спросит собственные учётные
            данные; с <KeyRound className="inline size-3.5" /> вход единый.
          </p>
        )}
      </main>
    </div>
  )
}
