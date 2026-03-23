/**
 * 4-панельный рабочий стол.
 * Desktop: 3 resizable панели (Raw + Core + Export) внутри MainLayout с sidebar.
 * Mobile: Tabs.
 */

import { useIsMobile } from '@/hooks/use-mobile'
import { useWorkspace, WorkspaceProvider } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { ResizableHandle } from '@/components/ui/resizable'
import { Panel, Group as PanelGroup } from 'react-resizable-panels'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { RawPanel } from './RawPanel'
import { CorePanel } from './CorePanel'
import { ExportPanel } from './ExportPanel'
import { OnboardingScreen } from './OnboardingScreen'
import { ClipboardList, Database, FileOutput } from 'lucide-react'

function WorkspaceContent() {
  const isMobile = useIsMobile()
  const settings = getSettings()
  const hasCredentials = !!settings.stsLogin && !!settings.stsPassword

  if (!hasCredentials) {
    return <OnboardingScreen />
  }

  if (isMobile) {
    return <MobileWorkspace />
  }

  return <DesktopWorkspace />
}

function DesktopWorkspace() {
  return (
    <div className="h-[calc(100vh-var(--header-height))] overflow-hidden">
      <PanelGroup orientation="horizontal" className="h-full">
        {/* Raw Panel */}
        <Panel defaultSize={22} minSize={16} maxSize={35}>
          <div className="h-full border-r border-border/30 bg-card/30">
            <RawPanel />
          </div>
        </Panel>

        <ResizableHandle />

        {/* Core Panel */}
        <Panel defaultSize={50} minSize={30}>
          <div className="h-full bg-background">
            <CorePanel />
          </div>
        </Panel>

        <ResizableHandle />

        {/* Export Panel */}
        <Panel defaultSize={28} minSize={18} maxSize={40}>
          <div className="h-full border-l border-border/30 bg-card/30">
            <ExportPanel />
          </div>
        </Panel>
      </PanelGroup>
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
