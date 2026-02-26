import { useParams, Link, useNavigate } from 'react-router-dom'
import { useEntry, useVerifyEntry, useTransferEntries, useDeleteEntry } from '@/hooks/useEntries'
import { DocumentPreview } from '@/components/data/DocumentPreview'
import { MetadataPanel } from '@/components/data/MetadataPanel'
import { HistoryTimeline } from '@/components/data/HistoryTimeline'
import { DocumentLinks } from '@/components/data/DocumentLinks'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DetailPageSkeleton } from '@/components/common/Skeletons'
import { toast } from 'sonner'

export function DataDetailPage() {
  const { category, id } = useParams<{ category: string; id: string }>()
  const navigate = useNavigate()
  const { data: entry, isLoading } = useEntry(id ?? '')
  const verifyEntry = useVerifyEntry()
  const transferEntries = useTransferEntries()
  const deleteEntry = useDeleteEntry()

  if (isLoading) return <DetailPageSkeleton />

  if (!entry) {
    return (
      <div className="flex items-center justify-center h-[50vh]">
        <p className="text-muted-foreground text-lg">Запись не найдена</p>
      </div>
    )
  }

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

  return (
    <div className="space-y-4">
      {/* Back link */}
      <Button variant="ghost" size="sm" asChild>
        <Link to={`/data/${category}`}>
          <ArrowLeft />
          Назад к списку
        </Link>
      </Button>

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
          />
          <DocumentLinks entryId={entry.id} allowAdd />
          <HistoryTimeline entry={entry} />
        </div>
      </div>
    </div>
  )
}
