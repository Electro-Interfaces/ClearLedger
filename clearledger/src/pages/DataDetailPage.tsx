import { useParams, Link, useNavigate } from 'react-router-dom'
import { useEntry, useVerifyEntry, useTransferEntries, useDeleteEntry, useArchiveEntry, useRestoreEntry, useExcludeEntry, useIncludeEntry } from '@/hooks/useEntries'
import { useEntryAudit } from '@/hooks/useAudit'
import { DocumentPreview } from '@/components/data/DocumentPreview'
import { MetadataPanel } from '@/components/data/MetadataPanel'
import { HistoryTimeline } from '@/components/data/HistoryTimeline'
import { DocumentLinks } from '@/components/data/DocumentLinks'
import { VersionHistory } from '@/components/data/VersionHistory'
import { ArrowLeft, FilePlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DetailPageSkeleton } from '@/components/common/Skeletons'
import { QueryError } from '@/components/common/QueryError'
import { toast } from 'sonner'
import { validateEntry } from '@/services/validationService'
import { useCompany } from '@/contexts/CompanyContext'

export function DataDetailPage() {
  const { category, id } = useParams<{ category: string; id: string }>()
  const navigate = useNavigate()
  const { company } = useCompany()
  const { data: entry, isLoading, isError, refetch } = useEntry(id ?? '')
  const verifyEntry = useVerifyEntry()
  const transferEntries = useTransferEntries()
  const deleteEntry = useDeleteEntry()
  const archiveEntry = useArchiveEntry()
  const restoreEntry = useRestoreEntry()
  const excludeEntry = useExcludeEntry()
  const includeEntry = useIncludeEntry()
  const { data: auditEvents } = useEntryAudit(id ?? '')

  if (isLoading) return <DetailPageSkeleton />
  if (isError) return <QueryError onRetry={() => refetch()} />

  if (!entry) {
    return (
      <div className="flex items-center justify-center h-[50vh]">
        <p className="text-muted-foreground text-lg">Запись не найдена</p>
      </div>
    )
  }

  const validation = validateEntry(entry, company.profileId)

  function handleVerify() {
    if (!id) return
    verifyEntry.mutate(id, {
      onSuccess: () => toast.success('Запись верифицирована'),
      onError: () => toast.error('Ошибка верификации'),
    })
  }

  function handleTransfer() {
    if (!id) return
    transferEntries.mutate([id], {
      onSuccess: () => toast.success('Запись передана в 1С'),
      onError: () => toast.error('Ошибка передачи'),
    })
  }

  function handleDelete() {
    if (!id) return
    deleteEntry.mutate(id, {
      onSuccess: () => {
        toast.success('Запись удалена')
        navigate(`/data/${category}`)
      },
      onError: () => toast.error('Ошибка удаления'),
    })
  }

  function handleArchive() {
    if (!id) return
    archiveEntry.mutate(id, {
      onSuccess: () => {
        toast.success('Запись архивирована')
        navigate(`/data/${category}`)
      },
      onError: () => toast.error('Ошибка архивирования'),
    })
  }

  function handleRestore() {
    if (!id) return
    restoreEntry.mutate(id, {
      onSuccess: () => toast.success('Запись восстановлена из архива'),
      onError: () => toast.error('Ошибка восстановления'),
    })
  }

  function handleExclude() {
    if (!id) return
    excludeEntry.mutate(id, {
      onSuccess: () => toast.success('Запись исключена из анализа'),
      onError: () => toast.error('Ошибка'),
    })
  }

  function handleInclude() {
    if (!id) return
    includeEntry.mutate(id, {
      onSuccess: () => toast.success('Запись возвращена в анализ'),
      onError: () => toast.error('Ошибка'),
    })
  }

  function handleNewVersion() {
    navigate(`/input?newVersionOf=${id}`)
  }

  return (
    <div className="space-y-4">
      {/* Back link */}
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to={`/data/${category}`}>
            <ArrowLeft />
            Назад к списку
          </Link>
        </Button>
        {entry.status !== 'archived' && (
          <Button variant="outline" size="sm" onClick={handleNewVersion}>
            <FilePlus />
            Новая версия
          </Button>
        )}
      </div>

      {/* Split layout: 60/40 on desktop, stacked on mobile */}
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-4">
        {/* Left: Document preview */}
        <DocumentPreview entry={entry} />

        {/* Right: Metadata + actions + History */}
        <div className="space-y-4">
          <MetadataPanel
            entry={entry}
            onVerify={entry.status === 'new' || entry.status === 'recognized' ? handleVerify : undefined}
            onTransfer={entry.status === 'verified' ? handleTransfer : undefined}
            onDelete={entry.status !== 'transferred' ? handleDelete : undefined}
            onArchive={entry.status !== 'archived' && entry.status !== 'transferred' ? handleArchive : undefined}
            onRestore={entry.status === 'archived' ? handleRestore : undefined}
            onExclude={entry.metadata._excluded !== 'true' ? handleExclude : undefined}
            onInclude={entry.metadata._excluded === 'true' ? handleInclude : undefined}
            validation={validation}
          />
          <VersionHistory entryId={entry.id} />
          <DocumentLinks entryId={entry.id} allowAdd />
          <HistoryTimeline entry={entry} auditEvents={auditEvents} />
        </div>
      </div>
    </div>
  )
}
