/**
 * Рабочий стол.
 * Вертикальное меню разделов + единая рабочая область (core) на всю ширину.
 */

import { lazy, Suspense, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Copy, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useMaxWidth } from '@/hooks/use-mobile'
import { EmptyState } from '@/components/common/EmptyState'
import { PRODUCT_SETUP_NOTE } from '@/config/spaceProducts'
import { useAppEnabled } from '@/hooks/useCompanyRegistry'
import { useCompany } from '@/contexts/CompanyContext'
import { useWorkspace, WorkspaceProvider, type CoreMode } from '@/contexts/WorkspaceContext'
import { useActiveMode } from '@/contexts/ActiveModeContext'
import { getSettings } from '@/services/settingsService'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { STORE_MODES } from '@/config/storeCatalog'
import { ACCOUNTING_MODES } from '@/config/moduleComponents'
import { OnboardingScreen } from './OnboardingScreen'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { WorkspaceModeSidebar } from './WorkspaceModeSidebar'
import { useVisibleSections } from './workspaceSections'

/**
 * Панели разделов — лениво. Статические импорты складывали ВСЕ рабочие места
 * (Учёт, Магазин с его 18 панелями, Топливо, Энергетику, Оборудование, Рынок)
 * в один чанк: 3,3 МБ / 864 кБ gzip грузились ещё до экрана входа. Человек
 * открывает один раздел за раз — остальные приезжают по мере переключения.
 */
const NormalizationPanel = lazy(() => import('./NormalizationPanel').then((m) => ({ default: m.NormalizationPanel })))
const ReconciliationPanel = lazy(() => import('./ReconciliationPanel').then((m) => ({ default: m.ReconciliationPanel })))
const ManagementPanel = lazy(() => import('./AccountingPanels').then((m) => ({ default: m.ManagementPanel })))
const FinancialPanel = lazy(() => import('./AccountingPanels').then((m) => ({ default: m.FinancialPanel })))
const AccountingPanel = lazy(() => import('./AccountingPanels').then((m) => ({ default: m.AccountingPanel })))
const TaxPanel = lazy(() => import('./AccountingPanels').then((m) => ({ default: m.TaxPanel })))
const StorePanel = lazy(() => import('./StorePanel').then((m) => ({ default: m.StorePanel })))
const StoreHelpPanel = lazy(() => import('./StorePanel').then((m) => ({ default: m.StoreHelpPanel })))
const StoreWindow = lazy(() => import('./StoreWindow').then((m) => ({ default: m.StoreWindow })))
const ExportLayerPanel = lazy(() => import('./ExportLayerPanel').then((m) => ({ default: m.ExportLayerPanel })))
// Рабочие места компании без объектов: «Реализация» и «Бухгалтерия».
const RevenuePanel = lazy(() => import('./OfficeRevenue').then((m) => ({ default: m.RevenuePanel })))
const ConnectView = lazy(() => import('./ConnectView').then((m) => ({ default: m.ConnectView })))
const REVENUE_MODES: CoreMode[] = ['rev_sales', 'rev_buyers', 'rev_catalog', 'rev_papers',
  'rev_money', 'rev_stock', 'rev_help']
const EconomyPanel = lazy(() => import('./OfficeEconomy').then((m) => ({ default: m.EconomyPanel })))
const ECONOMY_MODES: CoreMode[] = ['econ_result', 'econ_costs', 'econ_taxes', 'econ_help']
const BooksPanel = lazy(() => import('./OfficePanels').then((m) => ({ default: m.BooksPanel })))
const PerimeterPanel = lazy(() => import('./OfficePerimeter').then((m) => ({ default: m.PerimeterPanel })))

/**
 * Продукт в подключении: рабочего места ещё нет, меню тоже — только заставка.
 *
 * Пустой продукт всё равно виден в рельсе: он заведён в реестре пространства, ему
 * выдают права и его настраивают. Заставка честно говорит, что здесь пока пусто и
 * где эти функции сейчас, — вместо пустой рабочей области.
 */
/** Значение демо-доступа: клик копирует — на показе их набирают руками с экрана. */
function CopyValue({ value }: { value: string }) {
  return (
    <button type="button"
      onClick={() => {
        navigator.clipboard?.writeText(value)
          .then(() => toast.success('Скопировано'))
          .catch(() => toast.error('Не удалось скопировать'))
      }}
      title="Нажмите, чтобы скопировать"
      className="inline-flex items-center gap-1 rounded border border-border/60 bg-background px-1.5 py-0.5 font-mono text-[11px] transition-colors hover:border-primary/50 hover:text-primary">
      {value}
      <Copy className="size-3 shrink-0 opacity-60" />
    </button>
  )
}

export function ProductStub({ code }: { code: string }) {
  const note = PRODUCT_SETUP_NOTE[code]
  const { company } = useCompany()
  // Демо зовём только там, где боевого продукта нет: у ГИГ процессинг рабочий
  // (мост `processing`), и демо-стенд там сбивал бы с толку (замечание МАГа).
  const rivalEnabled = useAppEnabled(company?.id ?? '', note?.demo?.hideIfApp ?? '')
  if (!note) return null
  const demo = note.demo && !(note.demo.hideIfApp && rivalEnabled) ? note.demo : undefined
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="flex flex-col items-center">
        <EmptyState icon={note.icon} title={note.title} description={note.description}
          action={demo ? {
            label: demo.label,
            // Новая вкладка: демо — чужой стенд со своим входом, и возвращаться
            // человеку надо в своё пространство, а не «назад» из чужой системы.
            onClick: () => window.open(demo.url, '_blank', 'noopener,noreferrer'),
          } : undefined} />
        {demo && (
          <p className="mt-3 max-w-sm text-center text-xs leading-relaxed text-muted-foreground">
            {demo.note}
          </p>
        )}
        {demo?.accounts?.length ? (
          <div className="mt-3 w-full max-w-sm rounded-lg border border-dashed border-border/70 bg-muted/20 p-3">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Вход в демо
            </div>
            <div className="space-y-2">
              {demo.accounts.map((a) => (
                <div key={a.login} className="text-xs">
                  <div className="text-muted-foreground">{a.role}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                    <CopyValue value={a.login} />
                    <CopyValue value={a.password} />
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Данные вымышленные — стенд для показа, не боевая система.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  )
}

/**
 * Диспетчер разделов — один на обе раскладки (десктоп и телефон показывают
 * одно и то же рабочее место, различаются только обрамлением). Раньше этот
 * список был скопирован в оба компонента, и новый раздел приходилось заводить
 * дважды — половина забывалась.
 */
function ModePanel() {
  const { coreMode } = useWorkspace()
  return (
    <Suspense fallback={
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    }>
      {coreMode === 'normalize' && <NormalizationPanel />}
      {coreMode === 'reconcile' && <ReconciliationPanel />}
      {coreMode === 'management' && <ManagementPanel />}
      {/* Разделы того же продукта: панель одна, различаются составом пунктов
          (см. workspaceSections). У ЭЗС это «Сессии» и «Коммерция», у «Топлива» —
          «Аналитика», «Коммерция» и «Товародвижение». */}
      {coreMode === 'sales_sessions' && <ManagementPanel mode="sales_sessions" />}
      {coreMode === 'sales_commerce' && <ManagementPanel mode="sales_commerce" />}
      {coreMode === 'sales_goods' && <ManagementPanel mode="sales_goods" />}
      {/* «Помощь» — свод знания по продукту: у «Топлива» роутится общей панелью
          разделов, у «Магазина» своей (у него свой набор пунктов). */}
      {coreMode === 'sales_help' && <ManagementPanel mode="sales_help" />}
      {coreMode === 'operations' && <ManagementPanel mode="operations" />}
      {/* «Оборудование» и «Хозяйство» — разделы «Эксплуатации», та же панель. */}
      {coreMode === 'ops_equipment' && <ManagementPanel mode="ops_equipment" />}
      {coreMode === 'ops_economy' && <ManagementPanel mode="ops_economy" />}
      {/* «Работа» и «Аналитика» — два раздела одного продукта: панель одна,
          различаются составом пунктов (см. workspaceSections). */}
      {coreMode === 'projects' && <ManagementPanel mode="projects" />}
      {coreMode === 'projects_analytics' && <ManagementPanel mode="projects_analytics" />}
      {STORE_MODES.includes(coreMode) && <StorePanel />}
      {/* Окно пункта поверх экрана — рядом с панелью, а не внутри неё: панель
          перерисовывается сменой пункта и уносила бы окно с собой. */}
      {STORE_MODES.includes(coreMode) && <StoreWindow />}
      {coreMode === 'store_help' && <StoreHelpPanel />}
      {/* Корпоратив и маркетинг — продукты в подключении: их коммерческие
          разделы вернулись в «Продажи» (решение МАГа 28.07.2026). */}
      {coreMode === 'corporate' && <ProductStub code="corp" />}
      {coreMode === 'marketing' && <ManagementPanel mode="marketing" />}
      {coreMode === 'financial' && <FinancialPanel />}
      {/* Разделы «Бухгалтерии» — потоки и сквозное; панель одна, различаются
          составом пунктов (см. moduleComponents). */}
      {ACCOUNTING_MODES.includes(coreMode) && <AccountingPanel />}
      {coreMode === 'tax' && <TaxPanel />}
      {coreMode === 'export' && <ExportLayerPanel />}
      {/* Компания без объектов: четыре раздела «Реализации» — панель одна, различается
          вопросом к тем же документам бухгалтерии. */}
      {REVENUE_MODES.includes(coreMode) && <RevenuePanel />}
      {ECONOMY_MODES.includes(coreMode) && <EconomyPanel />}
      {(coreMode === 'books_ledger' || coreMode === 'books_primary'
        || coreMode === 'books_offbal') && <BooksPanel />}
      {coreMode.startsWith('per_') && <PerimeterPanel />}
      {/* «Подключения»: один раздел, его пункты — во второй колонке. Пока ветки не
          было, маршрут /connect (плитка стола, лаунчер) открывал рабочую область без
          содержимого. */}
      {coreMode === 'connect' && <ConnectView />}
    </Suspense>
  )
}

function WorkspaceContent() {
  // Компактная раскладка (горизонтальные полосы, без вертикального меню режимов)
  // для телефонов И планшетов ≤1024px — на десктопе вертикальное меню + core.
  const compact = useMaxWidth(1024)
  const settings = getSettings()
  const hasCredentials = !!settings.stsLogin && !!settings.stsPassword

  if (!hasCredentials) {
    return <OnboardingScreen />
  }

  return compact ? <MobileWorkspace /> : <DesktopWorkspace />
}

function DesktopWorkspace() {
  const { coreMode, lastReconcileResult } = useWorkspace()
  const reconResult = lastReconcileResult as { summary: { totalMstoVolume: number; totalMstoSum: number; totalMstoCount: number; totalTfVolume: number; totalTfSum: number; totalShiftNonCashVolume: number; mstoVsTfVolumeDiff: number; matched: number; mismatch: number; hasErrors: boolean } } | null
  const fmtN = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(n)

  return (
    <div className="h-full min-h-0 overflow-hidden flex">
      {/* Вертикальное меню разделов — во всю высоту рабочего стола, слева от строки фильтров */}
      <WorkspaceModeSidebar />

      {/* === Правая колонка === — строка фильтров сверху, над рабочей областью */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <WorkspaceToolbar />

        {/* === Рабочая область === — единый слой на всю ширину */}
        <div className="flex-1 min-h-0 bg-background flex flex-col overflow-hidden">
          {/* Полоса KPI сверки — показывается только в режиме сверки.
              Заголовок раздела убран: активный раздел и так виден в меню слева. */}
          {coreMode === 'reconcile' && reconResult && (
            <div className="flex items-center justify-end gap-1.5 px-4 py-2.5 border-b border-border">
              <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-card/50 border border-border/30">
                <span className="text-xs text-muted-foreground">MSTO</span>
                <span className="text-sm font-semibold">{fmtN(reconResult.summary.totalMstoVolume)} л</span>
                <span className="text-xs text-muted-foreground">{fmtN(reconResult.summary.totalMstoSum)} ₽</span>
              </div>
              <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-card/50 border border-border/30">
                <span className="text-xs text-muted-foreground">TF</span>
                <span className="text-sm font-semibold">{fmtN(reconResult.summary.totalTfVolume)} л</span>
              </div>
              <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-card/50 border border-border/30">
                <span className="text-xs text-muted-foreground">Смены</span>
                <span className="text-sm font-semibold">{fmtN(reconResult.summary.totalShiftNonCashVolume)} л</span>
              </div>
              <div className={`flex items-center gap-1 px-2 py-0.5 rounded border ${reconResult.summary.hasErrors ? 'bg-red-500/5 border-red-500/30' : 'bg-emerald-500/5 border-emerald-500/30'}`}>
                <span className="text-xs text-muted-foreground">Δ</span>
                <span className={`text-sm font-bold ${Math.abs(reconResult.summary.mstoVsTfVolumeDiff) > 1 ? 'text-red-500' : 'text-emerald-500'}`}>
                  {reconResult.summary.mstoVsTfVolumeDiff > 0 ? '+' : ''}{fmtN(reconResult.summary.mstoVsTfVolumeDiff)} л
                </span>
                <span className="text-xs text-muted-foreground">{reconResult.summary.matched}✓{reconResult.summary.mismatch > 0 ? ` ${reconResult.summary.mismatch}✗` : ''}</span>
              </div>
            </div>
          )}
          <div className="flex-1 overflow-hidden">
            <ModePanel />
          </div>
        </div>
      </div>
    </div>
  )
}

function MobileWorkspace() {
  // Мобильный рабочий стол: горизонтальные полосы «режимы» + «под-виды» вместо
  // десктопного вертикального меню; контент — тот же диспетчер по coreMode.
  const sections = useVisibleSections()
  const { coreMode, setCoreMode } = useWorkspace()
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSub = searchParams.get('sub')
  const active = sections.find((s) => s.mode === coreMode)
  const items = active?.items ?? []
  const activeSub = urlSub && items.some((i) => i.key === urlSub) ? urlSub : items[0]?.key
  const setSub = (key: string) => setSearchParams((prev) => {
    const n = new URLSearchParams(prev); n.set('sub', key); return n
  }, { replace: true })

  return (
    <div className="h-full min-h-0 flex flex-col">
      {/* Фильтр рабочей области (период/станции/…) — свайп без видимого скроллбара */}
      <div className="overflow-x-auto scrollbar-hide shrink-0"><WorkspaceToolbar /></div>

      {/* Режим — компактный селект (вместо длинной скролл-полосы), под-виды — свайп-полоса */}
      <div className="flex items-center gap-1.5 border-b border-border/50 bg-muted/20 px-2 py-1.5 shrink-0">
        {/* Одному разделу селект не нужен (приложение с закреплённым режимом) —
            на телефоне это лишняя строка поверх и без того узкого экрана. */}
        {sections.length > 1 && (
          <Select value={coreMode} onValueChange={(v) => setCoreMode(v as typeof coreMode)}>
            <SelectTrigger size="sm"
              className="h-9 min-w-0 flex-1 basis-0 gap-1.5 text-xs font-medium
                         [&>span]:truncate">
              {/* иконка приезжает из выбранного SelectItem через SelectValue */}
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {sections.map((s) => {
                const Icon = s.icon
                return (
                  <SelectItem key={s.mode} value={s.mode}>
                    <span className="flex items-center gap-2"><Icon className="h-3.5 w-3.5" />{s.label}</span>
                  </SelectItem>
                )
              })}
            </SelectContent>
          </Select>
        )}

        {/* Пункты раздела — ВТОРЫМ селектором, зависимым от первого.
            Была свайп-строка, и на телефоне она подводила: пункты уезжали за край,
            сколько их всего — неизвестно, а выбранный приходилось искать прокруткой
            (замечание МАГа 15.08.2026). Список показывает набор целиком, цель под
            палец, и пара «раздел → пункт» читается как одна мысль, а не как строка
            вкладок, у которой не видно конца. */}
        {items.length > 0 && (
          <Select value={activeSub} onValueChange={setSub}>
            <SelectTrigger size="sm"
              className="h-9 min-w-0 flex-1 basis-0 gap-1.5 text-xs font-medium
                         [&>span]:truncate">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {items.map((it) => (
                <SelectItem key={it.key} value={it.key}>{it.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Контент режима — тот же диспетчер, что на десктопе */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <ModePanel />
      </div>
    </div>
  )
}

/**
 * Рабочая область. Без `modes` — «Учёт» со всеми своими разделами; с `modes` — продукт
 * пространства на своём маршруте («Проекты», «Эксплуатация», «Сеть», «Финансы», «Данные»),
 * где доступны только его разделы.
 */
export function WorkspaceLayout({ modes }: { modes?: CoreMode[] } = {}) {
  return (
    <WorkspaceProvider lockModes={modes}>
      <ModeBeacon />
      <WorkspaceContent />
    </WorkspaceProvider>
  )
}

/**
 * Маячок открытого раздела для левой рельсы: она живёт снаружи рабочей области
 * и её состояния не видит, а подсветка обязана совпадать с тем, что на экране.
 * Ничего не рисует — только публикует текущий раздел наверх.
 */
function ModeBeacon() {
  const { coreMode } = useWorkspace()
  const { publishMode } = useActiveMode()
  useEffect(() => {
    publishMode(coreMode)
    return () => publishMode(null)
  }, [coreMode, publishMode])
  return null
}
