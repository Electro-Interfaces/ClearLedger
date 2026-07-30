/**
 * Рабочий стол.
 * Вертикальное меню разделов + единая рабочая область (core) на всю ширину.
 */

import { useSearchParams } from 'react-router-dom'
import { useMaxWidth } from '@/hooks/use-mobile'
import { EmptyState } from '@/components/common/EmptyState'
import { PRODUCT_SETUP_NOTE } from '@/config/spaceProducts'
import { useWorkspace, WorkspaceProvider, type CoreMode } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { NormalizationPanel } from './NormalizationPanel'
import { ReconciliationPanel } from './ReconciliationPanel'
import { ManagementPanel, FinancialPanel, AccountingPanel, TaxPanel } from './AccountingPanels'
import { StorePanel, StoreHelpPanel } from './StorePanel'
import { STORE_MODES } from '@/config/storeCatalog'
import { ExportLayerPanel } from './ExportLayerPanel'
import { OnboardingScreen } from './OnboardingScreen'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { WorkspaceModeSidebar } from './WorkspaceModeSidebar'
import { useVisibleSections } from './workspaceSections'

/**
 * Продукт в подключении: рабочего места ещё нет, меню тоже — только заставка.
 *
 * Пустой продукт всё равно виден в рельсе: он заведён в реестре пространства, ему
 * выдают права и его настраивают. Заставка честно говорит, что здесь пока пусто и
 * где эти функции сейчас, — вместо пустой рабочей области.
 */
export function ProductStub({ code }: { code: string }) {
  const note = PRODUCT_SETUP_NOTE[code]
  if (!note) return null
  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState icon={note.icon} title={note.title} description={note.description} />
    </div>
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
            {coreMode === 'store_help' && <StoreHelpPanel />}
            {/* Корпоратив и маркетинг — продукты в подключении: их коммерческие
                разделы вернулись в «Продажи» (решение МАГа 28.07.2026). */}
            {coreMode === 'corporate' && <ProductStub code="corp" />}
            {coreMode === 'marketing' && <ManagementPanel mode="marketing" />}
            {coreMode === 'financial' && <FinancialPanel />}
            {coreMode === 'accounting' && <AccountingPanel />}
            {coreMode === 'tax' && <TaxPanel />}
            {coreMode === 'export' && <ExportLayerPanel />}
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
            <SelectTrigger size="sm" className="h-8 w-auto shrink-0 gap-1.5 text-xs font-medium">
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

        {/* Под-виды активного режима — свайп без видимого скроллбара */}
        {items.length > 0 && (
          <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto scrollbar-hide">
            {items.map((it) => {
              const on = it.key === activeSub
              return (
                <button key={it.key} onClick={() => setSub(it.key)}
                  ref={(el) => { if (on && el) el.scrollIntoView({ inline: 'nearest', block: 'nearest' }) }}
                  // 28 px по высоте — мимо пальца. Ниже sm поднимаем цель до 40 px,
                  // на десктопе строка остаётся компактной.
                  className={`min-h-10 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs transition-colors sm:min-h-0 ${on ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground'}`}>
                  {it.label}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Контент режима — тот же диспетчер, что на десктопе */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {coreMode === 'normalize' && <NormalizationPanel />}
        {coreMode === 'reconcile' && <ReconciliationPanel />}
        {coreMode === 'management' && <ManagementPanel />}
        {coreMode === 'sales_sessions' && <ManagementPanel mode="sales_sessions" />}
        {coreMode === 'sales_commerce' && <ManagementPanel mode="sales_commerce" />}
        {coreMode === 'sales_goods' && <ManagementPanel mode="sales_goods" />}
        {coreMode === 'sales_help' && <ManagementPanel mode="sales_help" />}
        {coreMode === 'operations' && <ManagementPanel mode="operations" />}
        {coreMode === 'ops_equipment' && <ManagementPanel mode="ops_equipment" />}
        {coreMode === 'ops_economy' && <ManagementPanel mode="ops_economy" />}
        {coreMode === 'projects' && <ManagementPanel mode="projects" />}
        {STORE_MODES.includes(coreMode) && <StorePanel />}
        {coreMode === 'store_help' && <StoreHelpPanel />}
        {coreMode === 'corporate' && <ProductStub code="corp" />}
        {coreMode === 'marketing' && <ManagementPanel mode="marketing" />}
        {coreMode === 'financial' && <FinancialPanel />}
        {coreMode === 'accounting' && <AccountingPanel />}
        {coreMode === 'tax' && <TaxPanel />}
        {coreMode === 'export' && <ExportLayerPanel />}
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
      <WorkspaceContent />
    </WorkspaceProvider>
  )
}
