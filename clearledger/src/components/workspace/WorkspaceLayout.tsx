/**
 * 4-панельный рабочий стол.
 * Панели resizable + collapsible через react-resizable-panels.
 */

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePanelRef } from 'react-resizable-panels'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useWorkspace, WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { useCompany } from '@/contexts/CompanyContext'
import { getSettings } from '@/services/settingsService'
import { modeAllowed } from '@/config/accessModules'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { Button } from '@/components/ui/button'
import { NormalizationPanel } from './NormalizationPanel'
import { ReconciliationPanel } from './ReconciliationPanel'
import { ManagementPanel, FinancialPanel, AccountingPanel, TaxPanel } from './AccountingPanels'
import { StorePanel } from './StorePanel'
import { ExportLayerPanel } from './ExportLayerPanel'
import { ExportPanel } from './ExportPanel'
import { OnboardingScreen } from './OnboardingScreen'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { WorkspaceModeSidebar } from './WorkspaceModeSidebar'
import { EnergyExportDocsPanel } from './EnergySidePanels'
import { useWorkspaceSections } from './workspaceSections'
import {
  Database, FileOutput,
  PanelLeftClose, PanelLeftOpen,
  PanelRightClose, PanelRightOpen,
} from 'lucide-react'

function WorkspaceContent() {
  // Компактная раскладка (горизонтальные полосы, без вертикального меню режимов)
  // для телефонов И планшетов ≤1024px — на десктопе два боковых меню + resizable.
  const compact = useMaxWidth(1024)
  const settings = getSettings()
  const hasCredentials = !!settings.stsLogin && !!settings.stsPassword

  if (!hasCredentials) {
    return <OnboardingScreen />
  }

  return compact ? <MobileWorkspace /> : <DesktopWorkspace />
}

function DesktopWorkspace() {
  const coreRef = usePanelRef()
  const exportRef = usePanelRef()

  // Панель «Для 1С» по умолчанию свёрнута; core занимает почти всю ширину.
  const [coreSize, setCoreSize] = useState(97)
  const [exportSize, setExportSize] = useState(3)

  const ICON = 5
  const CORE_SIZE = '70%' as const
  const EXPORT_SIZE = '30%' as const
  const COLLAPSED_SIZE = '3%' as const

  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'

  const { exportDocs, coreMode, lastReconcileResult } = useWorkspace()
  const reconResult = lastReconcileResult as { summary: { totalMstoVolume: number; totalMstoSum: number; totalMstoCount: number; totalTfVolume: number; totalTfSum: number; totalShiftNonCashVolume: number; mstoVsTfVolumeDiff: number; matched: number; mismatch: number; hasErrors: boolean } } | null
  const fmtN = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(n)

  return (
    <div className="h-full min-h-0 overflow-hidden flex flex-col">
      <WorkspaceToolbar />

      <div className="flex-1 min-h-0 flex">
        {/* Вертикальное меню разделов рабочей области (виды учёта + Выгрузка) */}
        <WorkspaceModeSidebar />

        <ResizablePanelGroup orientation="horizontal" className="flex-1 min-w-0">
        {/* === Core Panel === — первый слой («Документы») вынесен в отдельный раздел /files */}
        <ResizablePanel
          panelRef={coreRef}
          defaultSize="97%"
          minSize="3%"
          onResize={(s) => setCoreSize(s.asPercentage)}
          className="bg-background"
        >
          {coreSize <= ICON ? (
            <div className="h-full flex flex-col items-center py-3 gap-3">
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => coreRef.current?.resize(CORE_SIZE)} title="Развернуть">
                <PanelLeftOpen className="h-3.5 w-3.5" />
              </Button>
              <Database className="h-4 w-4 text-muted-foreground" />
              <span className="text-xs text-muted-foreground font-medium" style={{ writingMode: 'vertical-lr' }}>
                Данные
              </span>
            </div>
          ) : (
            <div className="h-full flex flex-col overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 border-b border-border/50">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  {{ normalize: 'Нормализация', reconcile: 'Сверка данных', management: 'Продажи', operations: 'Управленческий', store: 'Магазин', financial: 'Финансовый учёт', accounting: 'Бухгалтерский учёт', tax: 'Налоговый учёт', export: isEnergy ? 'Выгрузка' : 'Выгрузка в 1С' }[coreMode]}
                </h2>

                {/* KPI результатов сверки */}
                {coreMode === 'reconcile' && reconResult && (
                  <div className="flex items-center gap-1.5">
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

                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => coreRef.current?.resize(COLLAPSED_SIZE)} title="Свернуть">
                  <PanelLeftClose className="h-3.5 w-3.5" />
                </Button>
              </div>
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
          )}
        </ResizablePanel>

        {/* === Export Panel === — слой ДОКУМЕНТОВ ДЛЯ ЗАГРУЗКИ (фуел: «Для 1С»; energy: «Для учётной системы») */}
        <>
          <ResizableHandle withHandle />

          <ResizablePanel
            panelRef={exportRef}
            defaultSize="3%"
            minSize="3%"
            onResize={(s) => setExportSize(s.asPercentage)}
            className="bg-muted/60"
          >
            {exportSize <= ICON ? (
              <div className="h-full flex flex-col items-center py-3 gap-3">
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => exportRef.current?.resize(EXPORT_SIZE)} title="Развернуть">
                  <PanelRightOpen className="h-3.5 w-3.5" />
                </Button>
                <div className="relative">
                  <FileOutput className="h-4 w-4 text-muted-foreground" />
                  {exportDocs.length > 0 && (
                    <span className="absolute -top-1.5 -right-2 bg-primary text-primary-foreground text-[8px] rounded-full h-3.5 min-w-[14px] flex items-center justify-center px-0.5">
                      {exportDocs.length}
                    </span>
                  )}
                </div>
                <span className="text-xs text-muted-foreground font-medium" style={{ writingMode: 'vertical-lr' }}>
                  {isEnergy ? 'Для учёта' : 'Для 1С'}
                </span>
              </div>
            ) : (
              <div className="h-full flex flex-col overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-border/50">
                  <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                    {isEnergy ? 'Для учётной системы' : 'Для 1С'}
                  </h2>
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => exportRef.current?.resize(COLLAPSED_SIZE)} title="Свернуть">
                    <PanelRightClose className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="flex-1 overflow-hidden">
                  {isEnergy ? <EnergyExportDocsPanel hideHeader /> : <ExportPanel hideHeader />}
                </div>
              </div>
            )}
          </ResizablePanel>
        </>
        </ResizablePanelGroup>
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
    <div className="h-full min-h-0 flex flex-col pb-14">
      {/* Фильтр рабочей области (период/станции/…) — прокрутка при переполнении */}
      <div className="overflow-x-auto shrink-0"><WorkspaceToolbar /></div>

      {/* Полоса режимов */}
      <div className="flex gap-1 overflow-x-auto border-b border-border/50 bg-muted/20 px-2 py-1.5 shrink-0">
        {sections.map((s) => {
          const Icon = s.icon
          const on = s.mode === coreMode
          return (
            <button key={s.mode} onClick={() => setCoreMode(s.mode)}
              className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs transition-colors ${on ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground'}`}>
              <Icon className="h-3.5 w-3.5 shrink-0" />{s.label}
            </button>
          )
        })}
      </div>

      {/* Полоса под-видов активного режима */}
      {items.length > 0 && (
        <div className="flex gap-1 overflow-x-auto border-b border-border/40 px-2 py-1 shrink-0">
          {items.map((it) => {
            const on = it.key === activeSub
            return (
              <button key={it.key} onClick={() => setSub(it.key)}
                className={`whitespace-nowrap rounded-md px-2.5 py-1 text-xs transition-colors ${on ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground'}`}>
                {it.label}
              </button>
            )
          })}
        </div>
      )}

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
