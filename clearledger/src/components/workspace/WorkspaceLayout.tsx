/**
 * Рабочий стол.
 * Вертикальное меню разделов + единая рабочая область (core) на всю ширину.
 */

import { useSearchParams } from 'react-router-dom'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useWorkspace, WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { useCompany } from '@/contexts/CompanyContext'
import { getSettings } from '@/services/settingsService'
import { modeAllowed } from '@/config/accessModules'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { NormalizationPanel } from './NormalizationPanel'
import { ReconciliationPanel } from './ReconciliationPanel'
import { ManagementPanel, FinancialPanel, AccountingPanel, TaxPanel } from './AccountingPanels'
import { StorePanel } from './StorePanel'
import { ExportLayerPanel } from './ExportLayerPanel'
import { OnboardingScreen } from './OnboardingScreen'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { WorkspaceModeSidebar } from './WorkspaceModeSidebar'
import { useWorkspaceSections } from './workspaceSections'

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
            {coreMode === 'operations' && <ManagementPanel mode="operations" />}
            {coreMode === 'store' && <StorePanel />}
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
  const { companyModules } = useCompany()
  const sections = useWorkspaceSections().filter((s) => modeAllowed(s.mode, companyModules))
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
        {coreMode === 'operations' && <ManagementPanel mode="operations" />}
        {coreMode === 'store' && <StorePanel />}
        {coreMode === 'financial' && <FinancialPanel />}
        {coreMode === 'accounting' && <AccountingPanel />}
        {coreMode === 'tax' && <TaxPanel />}
        {coreMode === 'export' && <ExportLayerPanel />}
      </div>
    </div>
  )
}

export function WorkspaceLayout() {
  return (
    <WorkspaceProvider>
      <WorkspaceContent />
    </WorkspaceProvider>
  )
}
