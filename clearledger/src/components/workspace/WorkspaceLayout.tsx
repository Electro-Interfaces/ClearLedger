/**
 * 4-панельный рабочий стол.
 * Панели resizable + collapsible через react-resizable-panels.
 */

import { useState } from 'react'
import { usePanelRef } from 'react-resizable-panels'
import { useIsMobile } from '@/hooks/use-mobile'
import { useWorkspace, WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable'
import { Button } from '@/components/ui/button'
import { RawPanel } from './RawPanel'
import { CorePanel } from './CorePanel'
import { ExportPanel } from './ExportPanel'
import { OnboardingScreen } from './OnboardingScreen'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import {
  ClipboardList, Database, FileOutput,
  PanelLeftClose, PanelLeftOpen,
  PanelRightClose, PanelRightOpen,
} from 'lucide-react'

function WorkspaceContent() {
  const isMobile = useIsMobile()
  const settings = getSettings()
  const hasCredentials = !!settings.stsLogin && !!settings.stsPassword

  if (!hasCredentials) {
    return <OnboardingScreen />
  }

  return isMobile ? <MobileWorkspace /> : <DesktopWorkspace />
}

function DesktopWorkspace() {
  const rawRef = usePanelRef()
  const coreRef = usePanelRef()
  const exportRef = usePanelRef()

  const [rawSize, setRawSize] = useState(20)
  const [coreSize, setCoreSize] = useState(55)
  const [exportSize, setExportSize] = useState(25)

  const ICON = 5
  const RAW_SIZE = '20%' as const
  const CORE_SIZE = '55%' as const
  const EXPORT_SIZE = '25%' as const
  const COLLAPSED_SIZE = '3%' as const

  const { exportDocs, selectedShiftNumber } = useWorkspace()

  return (
    <div className="h-[calc(100vh-var(--header-height))] overflow-hidden flex flex-col">
      <WorkspaceToolbar />

      <ResizablePanelGroup orientation="horizontal" className="flex-1">
        {/* === Raw Panel === */}
        <ResizablePanel
          panelRef={rawRef}
          defaultSize="20%"
          minSize="3%"
          onResize={(s) => setRawSize(s.asPercentage)}
          className="bg-card/30"
        >
          {rawSize <= ICON ? (
            <div className="h-full flex flex-col items-center py-3 gap-3">
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => rawRef.current?.resize(RAW_SIZE)} title="Развернуть">
                <PanelLeftOpen className="h-3.5 w-3.5" />
              </Button>
              <ClipboardList className="h-4 w-4 text-muted-foreground" />
              <span className="text-[10px] text-muted-foreground font-medium" style={{ writingMode: 'vertical-lr' }}>
                Загруженные
              </span>
            </div>
          ) : (
            <div className="h-full flex flex-col overflow-hidden">
              <div className="flex-1 overflow-hidden">
                <RawPanel
                  hideHeader
                  collapseButton={
                    <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={() => rawRef.current?.resize(COLLAPSED_SIZE)} title="Свернуть">
                      <PanelLeftClose className="h-3.5 w-3.5" />
                    </Button>
                  }
                />
              </div>
            </div>
          )}
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* === Core Panel === */}
        <ResizablePanel
          panelRef={coreRef}
          defaultSize="55%"
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
              <span className="text-[10px] text-muted-foreground font-medium" style={{ writingMode: 'vertical-lr' }}>
                Данные
              </span>
            </div>
          ) : (
            <div className="h-full flex flex-col overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 border-b border-border/50">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  {selectedShiftNumber ? `Смена №${selectedShiftNumber}` : 'Нормализованные данные'}
                </h2>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => coreRef.current?.resize(COLLAPSED_SIZE)} title="Свернуть">
                  <PanelLeftClose className="h-3.5 w-3.5" />
                </Button>
              </div>
              <div className="flex-1 overflow-hidden">
                <CorePanel hideHeader />
              </div>
            </div>
          )}
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* === Export Panel === */}
        <ResizablePanel
          panelRef={exportRef}
          defaultSize="25%"
          minSize="3%"
          onResize={(s) => setExportSize(s.asPercentage)}
          className="bg-card/30"
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
              <span className="text-[10px] text-muted-foreground font-medium" style={{ writingMode: 'vertical-lr' }}>
                Для 1С
              </span>
            </div>
          ) : (
            <div className="h-full flex flex-col overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-border/50">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  Для 1С
                </h2>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => exportRef.current?.resize(COLLAPSED_SIZE)} title="Свернуть">
                  <PanelRightClose className="h-3.5 w-3.5" />
                </Button>
              </div>
              <div className="flex-1 overflow-hidden">
                <ExportPanel hideHeader />
              </div>
            </div>
          )}
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}

function MobileWorkspace() {
  const { activeTab, setActiveTab, exportDocs } = useWorkspace()

  return (
    <div className="h-full pb-14">
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'raw' | 'core' | 'export')}>
        <TabsList className="w-full rounded-none border-b h-10 bg-card">
          <TabsTrigger value="raw" className="flex-1 gap-1.5 text-xs">
            <ClipboardList className="h-3.5 w-3.5" />
            Смены
          </TabsTrigger>
          <TabsTrigger value="core" className="flex-1 gap-1.5 text-xs">
            <Database className="h-3.5 w-3.5" />
            Детали
          </TabsTrigger>
          <TabsTrigger value="export" className="flex-1 gap-1.5 text-xs">
            <FileOutput className="h-3.5 w-3.5" />
            Для 1С
            {exportDocs.length > 0 && (
              <span className="ml-1 bg-primary text-primary-foreground text-[9px] rounded-full h-4 min-w-[16px] flex items-center justify-center px-1">
                {exportDocs.length}
              </span>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="raw" className="mt-0 h-[calc(100vh-8rem)]">
          <RawPanel />
        </TabsContent>
        <TabsContent value="core" className="mt-0 h-[calc(100vh-8rem)]">
          <CorePanel />
        </TabsContent>
        <TabsContent value="export" className="mt-0 h-[calc(100vh-8rem)]">
          <ExportPanel />
        </TabsContent>
      </Tabs>
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
