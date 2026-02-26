import { useParams, useNavigate, Link } from 'react-router-dom'
import { useMemo } from 'react'
import { useInbox, useEntry, useVerifyEntry, useRejectEntry } from '@/hooks/useEntries'
import { DocumentPreview } from '@/components/data/DocumentPreview'
import { VerificationForm } from '@/components/inbox/VerificationForm'
import { InboxNavigation } from '@/components/inbox/InboxNavigation'
import { DocumentLinks } from '@/components/data/DocumentLinks'
import { Button } from '@/components/ui/button'
import { ArrowLeft } from 'lucide-react'

export function InboxDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: entry, isLoading } = useEntry(id ?? '')
  const { data: inboxEntries = [] } = useInbox()
  const verifyEntry = useVerifyEntry()
  const rejectEntry = useRejectEntry()

  const currentIndex = useMemo(
    () => inboxEntries.findIndex((e) => e.id === id),
    [inboxEntries, id],
  )

  function navigateToIndex(index: number) {
    const target = inboxEntries[index]
    if (target) navigate(`/inbox/${target.id}`, { replace: true })
  }

  function goToNextOrBack() {
    // Если есть следующий — переходим к нему, иначе к предыдущему, иначе к inbox
    if (inboxEntries.length <= 1) {
      navigate('/inbox')
      return
    }
    const nextIdx = currentIndex < inboxEntries.length - 1 ? currentIndex + 1 : currentIndex - 1
    const target = inboxEntries[nextIdx]
    if (target) {
      navigate(`/inbox/${target.id}`, { replace: true })
    } else {
      navigate('/inbox')
    }
  }

  function handleVerify() {
    if (!id) return
    verifyEntry.mutate(id, {
      onSuccess: () => goToNextOrBack(),
    })
  }

  function handlePostpone() {
    // Просто переходим к следующей записи без изменения статуса
    if (currentIndex < inboxEntries.length - 1) {
      navigateToIndex(currentIndex + 1)
    } else if (currentIndex > 0) {
      navigateToIndex(currentIndex - 1)
    } else {
      navigate('/inbox')
    }
  }

  function handleReject(reason: string) {
    if (!id) return
    rejectEntry.mutate({ id, reason }, {
      onSuccess: () => goToNextOrBack(),
    })
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[50vh]">
        <p className="text-muted-foreground">Загрузка...</p>
      </div>
    )
  }

  if (!entry) {
    return (
      <div className="flex flex-col items-center justify-center h-[50vh] gap-4">
        <p className="text-muted-foreground text-lg">Запись не найдена</p>
        <Button variant="ghost" asChild>
          <Link to="/inbox">
            <ArrowLeft />
            Назад ко Входящим
          </Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header: Back + Navigation */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/inbox">
            <ArrowLeft />
            Входящие
          </Link>
        </Button>

        {inboxEntries.length > 0 && (
          <InboxNavigation
            currentIndex={Math.max(0, currentIndex)}
            total={inboxEntries.length}
            onPrevious={() => navigateToIndex(currentIndex - 1)}
            onNext={() => navigateToIndex(currentIndex + 1)}
          />
        )}
      </div>

      {/* Split view: 60% preview / 40% form */}
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-4">
        <div className="space-y-4">
          <DocumentPreview entry={entry} />
          <DocumentLinks entryId={entry.id} />
        </div>
        <VerificationForm
          entry={entry}
          onVerify={handleVerify}
          onPostpone={handlePostpone}
          onReject={handleReject}
          isLoading={verifyEntry.isPending || rejectEntry.isPending}
        />
      </div>
    </div>
  )
}
