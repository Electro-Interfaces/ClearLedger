/**
 * 4-панельный рабочий стол.
 * Каждая панель сворачивается до узкой полоски с иконками.
 */

import { useState } from 'react'
import { useIsMobile } from '@/hooks/use-mobile'
import { useWorkspace, WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Group as ResizablePanelGroup, Panel as ResizablePanel, Separator as ResizableHandle } from 'react-resizable-panels'
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

/** Свёрнутая полоска панели */
function CollapsedStrip({
  icon: Icon,
  label,
  side,
  onClick,
  badge,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  side: 'left' | 'right'
  onClick: () => void
  badge?: number
}) {
  const ExpandIcon = side === 'left' ? PanelLeftOpen : PanelRightOpen

  return (
    <div className="w-10 h-full flex flex-col items-center py-2 gap-2 border-border/40 bg-card/50"
      style={{ borderRight: side === 'left' ? '1px solid hsl(var(--border) / 0.4)' : undefined,
               borderLeft: side === 'right' ? '1px solid hsl(var(--border) / 0.4)' : undefined }}>
      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClick} title={label}>
        <ExpandIcon className="h-4 w-4" />
      </Button>
      <div className="flex flex-col items-center gap-3 mt-2">
        <div className="relative">
          <Icon className="h-4 w-4 text-muted-foreground" />
          {badge != null && badge > 0 && (
            <span className="absolute -top-1.5 -right-2 bg-primary text-primary-foreground text-[8px] rounded-full h-3.5 min-w-[14px] flex items-center justify-center px-0.5">
              {badge}
            </span>
          )}
        </div>
      </div>
      <div className="mt-auto">
        <span
          className="text-[10px] text-muted-foreground font-medium"
          style={{ writingMode: 'vertical-lr', textOrientation: 'mixed' }}
        >
          {label}
        </span>
      </div>
    </div>
  )
}

function DesktopWorkspace() {
  const [rawOpen, setRawOpen] = useState(true)
  const [coreOpen, setCoreOpen] = useState(true)
  const [exportOpen, setExportOpen] = useState(true)
  const { exportDocs, selectedShiftNumber } = useWorkspace()

  return (
    <div className="h-[calc(100vh-var(--header-height))] overflow-hidden flex flex-col">
      {/* Общий тулбар над всеми панелями */}
      <WorkspaceToolbar />

      {/* 3 resizable панели */}
      <ResizablePanelGroup orientation="horizontal" className="flex-1 overflow-hidden">
        {/* Raw Panel */}
        {rawOpen ? (
          <>
            <ResizablePanel defaultSize={20} minSize={15} maxSize={35} className="bg-card/30">
              <div className="h-full flex flex-col overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-border/50">
                  <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                    Загруженные
                  </h2>
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setRawOpen(false)} title="Свернуть">
                    <PanelLeftClose className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="flex-1 overflow-hidden">
                  <RawPanel hideHeader />
                </div>
              </div>
            </ResizablePanel>
            <ResizableHandle />
          </>
        ) : (
          <CollapsedStrip
            icon={ClipboardList}
            label="Загруженные"
            side="left"
            onClick={() => setRawOpen(true)}
          />
        )}

        {/* Core Panel */}
        {coreOpen ? (
          <>
            <ResizablePanel defaultSize={55} minSize={30} className="bg-background">
              <div className="h-full flex flex-col overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2 border-b border-border/50">
                  <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                    {selectedShiftNumber ? `Смена №${selectedShiftNumber}` : 'Нормализованные данные'}
                  </h2>
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setCoreOpen(false)} title="Свернуть">
                    <PanelLeftClose className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="flex-1 overflow-hidden">
                  <CorePanel hideHeader />
                </div>
              </div>
            </ResizablePanel>
            <ResizableHandle />
          </>
        ) : (
          <CollapsedStrip
            icon={Database}
            label="Данные"
            side="left"
            onClick={() => setCoreOpen(true)}
          />
        )}

        {/* Export Panel */}
        {exportOpen ? (
          <ResizablePanel defaultSize={25} minSize={15} maxSize={40} className="bg-card/30">
            <div className="h-full flex flex-col overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-border/50">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  Для 1С
                </h2>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setExportOpen(false)} title="Свернуть">
                  <PanelRightClose className="h-3.5 w-3.5" />
                </Button>
              </div>
              <div className="flex-1 overflow-hidden">
                <ExportPanel hideHeader />
              </div>
            </div>
          </ResizablePanel>
        ) : (
          <CollapsedStrip
            icon={FileOutput}
            label="Для 1С"
            side="right"
            onClick={() => setExportOpen(true)}
            badge={exportDocs.length}
          />
        )}
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
