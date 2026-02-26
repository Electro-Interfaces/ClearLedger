import { useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInbox, useVerifyEntry, useRejectEntry } from '@/hooks/useEntries'
import { InboxTable } from '@/components/inbox/InboxTable'
import { InboxToolbar, type InboxFilters } from '@/components/inbox/InboxToolbar'
import { TableSkeleton } from '@/components/common/Skeletons'
import { EmptyState } from '@/components/common/EmptyState'
import { QueryError } from '@/components/common/QueryError'
import { Button } from '@/components/ui/button'
import { Check, X, Inbox } from 'lucide-react'

export function InboxPage() {
  const navigate = useNavigate()
  const { data: inboxEntries = [], isLoading, isError, refetch } = useInbox()
  const verifyEntry = useVerifyEntry()
  const rejectEntry = useRejectEntry()

  const [filters, setFilters] = useState<InboxFilters>({
    search: '',
    source: 'all',
    status: 'all',
  })
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const filteredEntries = useMemo(() => {
    return inboxEntries.filter((e) => {
      if (filters.search && !e.title.toLowerCase().includes(filters.search.toLowerCase())) return false
      if (filters.source !== 'all' && e.source !== filters.source) return false
      if (filters.status !== 'all' && e.status !== filters.status) return false
      return true
    })
  }, [inboxEntries, filters])

  const handleRowClick = useCallback(
    (id: string) => navigate(`/inbox/${id}`),
    [navigate],
  )

  const handleVerify = useCallback(
    (id: string) => verifyEntry.mutate(id),
    [verifyEntry],
  )

  const handleReject = useCallback(
    (id: string) => rejectEntry.mutate({ id, reason: 'Отклонено из очереди' }),
    [rejectEntry],
  )

  const handleBatchVerify = useCallback(() => {
    for (const id of selectedIds) {
      verifyEntry.mutate(id)
    }
    setSelectedIds(new Set())
  }, [selectedIds, verifyEntry])

  const handleBatchReject = useCallback(() => {
    for (const id of selectedIds) {
      rejectEntry.mutate({ id, reason: 'Массовое отклонение' })
    }
    setSelectedIds(new Set())
  }, [selectedIds, rejectEntry])

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Входящие</h1>
        <TableSkeleton rows={6} />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Входящие</h1>
        <QueryError onRetry={() => refetch()} />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">Входящие</h1>
          {inboxEntries.length > 0 && (
            <span className="inline-flex items-center rounded-full bg-primary/15 px-2.5 py-0.5 text-sm font-medium text-primary">
              {inboxEntries.length}
            </span>
          )}
        </div>
      </div>

      <InboxToolbar filters={filters} onFiltersChange={setFilters} />

      {/* Batch actions */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-lg border bg-card">
          <span className="text-sm text-muted-foreground">
            Выбрано: <span className="font-medium text-foreground">{selectedIds.size}</span>
          </span>
          <Button
            size="sm"
            onClick={handleBatchVerify}
            className="bg-green-600 hover:bg-green-700 text-white"
          >
            <Check className="size-4" />
            Верифицировать все
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleBatchReject}
            className="text-red-500 hover:text-red-400"
          >
            <X className="size-4" />
            Отклонить все
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedIds(new Set())}
          >
            Снять выделение
          </Button>
        </div>
      )}

      {filteredEntries.length === 0 && !isLoading ? (
        <EmptyState
          icon={Inbox}
          title="Очередь пуста"
          description="Все записи обработаны. Загрузите новые документы для обработки."
        />
      ) : (
        <InboxTable
          entries={filteredEntries}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onRowClick={handleRowClick}
          onVerify={handleVerify}
          onReject={handleReject}
        />
      )}
    </div>
  )
}
