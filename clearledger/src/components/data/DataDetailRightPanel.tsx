/**
 * DataDetailRightPanel — правая панель DataDetailPage.
 *
 * MetadataPanel всегда видна сверху (основная задача — метаданные + действия).
 * Остальное — в табы: Версии, Комплект, Связи, Техн., История.
 */

import { MetadataPanel } from './MetadataPanel'
import { VersionHistory } from './VersionHistory'
import { BundleTreeCard } from './BundleTreeCard'
import { BundleSuggestionsPanel } from './BundleSuggestionsPanel'
import { DocumentLinks } from './DocumentLinks'
import { TechnicalInfoCard } from './TechnicalInfoCard'
import { HistoryTimeline } from './HistoryTimeline'
import { AuditJournal } from '@/components/common/AuditJournal'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { useEntryAudit } from '@/hooks/useAudit'
import { useBundleTree } from '@/hooks/useBundle'
import { isInBundle } from '@/services/bundleService'
import { FolderTree, FileCode, History, Link2, GitBranch } from 'lucide-react'
import type { DataEntry, AuditEvent } from '@/types'
import type { ValidationResult } from '@/services/validationService'

interface DataDetailRightPanelProps {
  entry: DataEntry
  validation: ValidationResult
  auditEvents?: AuditEvent[]
  onVerify?: () => void
  onTransfer?: () => void
  onDelete?: () => void
  onArchive?: () => void
  onRestore?: () => void
  onExclude?: () => void
  onInclude?: () => void
}

export function DataDetailRightPanel({
  entry,
  validation,
  auditEvents,
  onVerify,
  onTransfer,
  onDelete,
  onArchive,
  onRestore,
  onExclude,
  onInclude,
}: DataDetailRightPanelProps) {
  const { data: entryAudit = [] } = useEntryAudit(entry.id)
  const inBundle = isInBundle(entry)
  const { data: tree } = useBundleTree(entry.id)

  const bundleCount = tree?.totalCount ?? 0
  const auditCount = (auditEvents ?? entryAudit).length

  // Умный дефолт: если есть бандл → «bundle», иначе → «versions»
  const defaultTab = inBundle && bundleCount > 0 ? 'bundle' : 'versions'

  return (
    <div className="flex flex-col gap-3">
      {/* MetadataPanel — всегда видна */}
      <MetadataPanel
        entry={entry}
        onVerify={onVerify}
        onTransfer={onTransfer}
        onDelete={onDelete}
        onArchive={onArchive}
        onRestore={onRestore}
        onExclude={onExclude}
        onInclude={onInclude}
        validation={validation}
      />

      {/* Табы: Версии | Комплект | Связи | Техн. | История */}
      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="w-full">
          <TabsTrigger value="versions" className="flex-1 gap-1">
            <GitBranch className="size-3.5" />
            <span className="hidden sm:inline">Версии</span>
          </TabsTrigger>
          <TabsTrigger value="bundle" className="flex-1 gap-1">
            <FolderTree className="size-3.5" />
            <span className="hidden sm:inline">Комплект</span>
            {bundleCount > 0 && (
              <Badge variant="secondary" className="text-[10px] px-1 py-0 ml-0.5">
                {bundleCount}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="links" className="flex-1 gap-1">
            <Link2 className="size-3.5" />
            <span className="hidden sm:inline">Связи</span>
          </TabsTrigger>
          <TabsTrigger value="tech" className="flex-1 gap-1">
            <FileCode className="size-3.5" />
            <span className="hidden sm:inline">Техн.</span>
          </TabsTrigger>
          <TabsTrigger value="history" className="flex-1 gap-1">
            <History className="size-3.5" />
            <span className="hidden sm:inline">История</span>
            {auditCount > 0 && (
              <Badge variant="secondary" className="text-[10px] px-1 py-0 ml-0.5">
                {auditCount}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="versions">
          <ScrollArea className="max-h-[40vh]">
            <div className="pr-2">
              <VersionHistory entryId={entry.id} />
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="bundle">
          <ScrollArea className="max-h-[40vh]">
            <div className="space-y-3 pr-2">
              <BundleTreeCard entry={entry} />
              <BundleSuggestionsPanel entry={entry} />
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="links">
          <ScrollArea className="max-h-[40vh]">
            <div className="pr-2">
              <DocumentLinks entryId={entry.id} allowAdd />
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="tech">
          <ScrollArea className="max-h-[40vh]">
            <div className="pr-2">
              <TechnicalInfoCard entry={entry} />
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="history">
          <ScrollArea className="max-h-[40vh]">
            <div className="space-y-3 pr-2">
              <HistoryTimeline entry={entry} auditEvents={auditEvents} />
              <AuditJournal entryId={entry.id} />
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}
