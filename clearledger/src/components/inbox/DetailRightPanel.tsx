/**
 * DetailRightPanel — правая панель InboxDetailPage.
 *
 * VerificationForm всегда видна сверху (основная задача верификации).
 * Остальные компоненты организованы в табы: Комплект, Техн., Аудит.
 */

import { VerificationForm, type VerifyPayload } from './VerificationForm'
import { BundleTreeCard } from '@/components/data/BundleTreeCard'
import { BundleSuggestionsPanel } from '@/components/data/BundleSuggestionsPanel'
import { TechnicalInfoCard } from '@/components/data/TechnicalInfoCard'
import { AuditJournal } from '@/components/common/AuditJournal'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { useEntryAudit } from '@/hooks/useAudit'
import { useBundleTree } from '@/hooks/useBundle'
import { isInBundle } from '@/services/bundleService'
import { FolderTree, FileCode, History } from 'lucide-react'
import type { DataEntry } from '@/types'

interface DetailRightPanelProps {
  entry: DataEntry
  onVerify: (payload: VerifyPayload) => void
  onPostpone: () => void
  onReject: (reason: string) => void
  isLoading?: boolean
}

export function DetailRightPanel({
  entry,
  onVerify,
  onPostpone,
  onReject,
  isLoading,
}: DetailRightPanelProps) {
  const { data: auditEvents = [] } = useEntryAudit(entry.id)
  const inBundle = isInBundle(entry)
  const { data: tree } = useBundleTree(entry.id)

  const bundleCount = tree?.totalCount ?? 0
  const auditCount = auditEvents.length

  // Умный дефолт: если есть бандл → «bundle», иначе «tech»
  const defaultTab = inBundle && bundleCount > 0 ? 'bundle' : 'tech'

  return (
    <div className="flex flex-col gap-3">
      {/* VerificationForm — всегда видна */}
      <VerificationForm
        entry={entry}
        onVerify={onVerify}
        onPostpone={onPostpone}
        onReject={onReject}
        isLoading={isLoading}
      />

      {/* Табы: Комплект | Техн. | Аудит */}
      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="w-full">
          <TabsTrigger value="bundle" className="flex-1 gap-1.5">
            <FolderTree className="size-3.5" />
            <span className="hidden sm:inline">Комплект</span>
            {bundleCount > 0 && (
              <Badge variant="secondary" className="text-[10px] px-1 py-0 ml-0.5">
                {bundleCount}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="tech" className="flex-1 gap-1.5">
            <FileCode className="size-3.5" />
            <span className="hidden sm:inline">Техн.</span>
          </TabsTrigger>
          <TabsTrigger value="audit" className="flex-1 gap-1.5">
            <History className="size-3.5" />
            <span className="hidden sm:inline">Аудит</span>
            {auditCount > 0 && (
              <Badge variant="secondary" className="text-[10px] px-1 py-0 ml-0.5">
                {auditCount}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="bundle">
          <ScrollArea className="max-h-[40vh]">
            <div className="space-y-3 pr-2">
              <BundleTreeCard entry={entry} />
              <BundleSuggestionsPanel entry={entry} />
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

        <TabsContent value="audit">
          <ScrollArea className="max-h-[40vh]">
            <div className="pr-2">
              <AuditJournal entryId={entry.id} />
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}
