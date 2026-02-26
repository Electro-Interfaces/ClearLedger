import { useParams, useNavigate, Link } from 'react-router-dom'
import { useMemo, useEffect } from 'react'
import { useInbox, useEntry, useVerifyEntry, useRejectEntry, useUpdateEntry } from '@/hooks/useEntries'
import { DocumentPreview } from '@/components/data/DocumentPreview'
import { VerificationForm, type VerifyPayload } from '@/components/inbox/VerificationForm'
import { InboxNavigation } from '@/components/inbox/InboxNavigation'
import { DocumentLinks } from '@/components/data/DocumentLinks'
import { Button } from '@/components/ui/button'
import { ArrowLeft } from 'lucide-react'
import { AuditJournal } from '@/components/common/AuditJournal'
import { SplitViewSkeleton } from '@/components/common/Skeletons'
import { QueryError } from '@/components/common/QueryError'
import { toast } from 'sonner'

export function InboxDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: entry, isLoading, isError, refetch } = useEntry(id ?? '')
  const { data: inboxEntries = [] } = useInbox()
  const updateEntry = useUpdateEntry()
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

  function handleVerify(payload: VerifyPayload) {
    if (!id || !entry) return
    // Сохраняем изменённые поля перед верификацией
    const updates: Record<string, unknown> = {}
    if (payload.categoryId !== entry.categoryId) updates.categoryId = payload.categoryId
    if (payload.subcategoryId !== entry.subcategoryId) updates.subcategoryId = payload.subcategoryId

    // Мержим метаданные: отредактированные + комментарий
    const metaChanged = payload.metadata && JSON.stringify(payload.metadata) !== JSON.stringify(entry.metadata)
    if (metaChanged || payload.comment) {
      updates.metadata = {
        ...(payload.metadata ?? entry.metadata),
        ...(payload.comment ? { verifyComment: payload.comment } : {}),
      }
    }

    const doVerify = () => {
      verifyEntry.mutate(id, {
        onSuccess: () => {
          toast.success('Запись верифицирована')
          goToNextOrBack()
        },
        onError: () => toast.error('Ошибка верификации'),
      })
    }

    if (Object.keys(updates).length > 0) {
      updateEntry.mutate({ id, updates }, { onSuccess: doVerify, onError: () => toast.error('Ошибка сохранения') })
    } else {
      doVerify()
    }
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
      onSuccess: () => {
        toast.success('Запись отклонена')
        goToNextOrBack()
      },
      onError: () => toast.error('Ошибка отклонения'),
    })
  }

  // Keyboard shortcuts: J/ArrowDown=next, K/ArrowUp=prev, S=skip
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Игнорируем если фокус на input/textarea/select
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      switch (e.key.toLowerCase()) {
        case 'j':
        case 'arrowdown':
          e.preventDefault()
          if (currentIndex < inboxEntries.length - 1) navigateToIndex(currentIndex + 1)
          break
        case 'k':
        case 'arrowup':
          e.preventDefault()
          if (currentIndex > 0) navigateToIndex(currentIndex - 1)
          break
        case 's':
          e.preventDefault()
          handlePostpone()
          break
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [currentIndex, inboxEntries.length])

  if (isLoading) return <SplitViewSkeleton />
  if (isError) return <QueryError onRetry={() => refetch()} />

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

        <div className="flex items-center gap-3">
          {inboxEntries.length > 0 && (
            <InboxNavigation
              currentIndex={Math.max(0, currentIndex)}
              total={inboxEntries.length}
              onPrevious={() => navigateToIndex(currentIndex - 1)}
              onNext={() => navigateToIndex(currentIndex + 1)}
            />
          )}
          <span className="hidden lg:inline text-xs text-muted-foreground">
            J/K — навигация, S — пропустить
          </span>
        </div>
      </div>

      {/* Split view: 60% preview / 40% form */}
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-4">
        <div className="space-y-4">
          <DocumentPreview entry={entry} />
          <DocumentLinks entryId={entry.id} />
        </div>
        <div className="space-y-4">
        <VerificationForm
          entry={entry}
          onVerify={handleVerify}
          onPostpone={handlePostpone}
          onReject={handleReject}
          isLoading={updateEntry.isPending || verifyEntry.isPending || rejectEntry.isPending}
        />
        <AuditJournal entryId={entry.id} />
        </div>
      </div>
    </div>
  )
}
