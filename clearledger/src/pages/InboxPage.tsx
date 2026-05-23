import { useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInbox, useVerifyEntry, useRejectEntry, useUpdateEntry, useSetDocPurpose, useAuditorVerify } from '@/hooks/useEntries'
import { useCompany } from '@/contexts/CompanyContext'
import { InboxTable } from '@/components/inbox/InboxTable'
import { InboxToolbar, type InboxFilters, type GroupBy, defaultInboxFilters } from '@/components/inbox/InboxToolbar'
import { InboxStatsBar } from '@/components/inbox/InboxStatsBar'
import { TableSkeleton } from '@/components/common/Skeletons'
import { EmptyState } from '@/components/common/EmptyState'
import { QueryError } from '@/components/common/QueryError'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Check, X, Inbox, ChevronDown, FolderOpen, Target, ShieldCheck } from 'lucide-react'
import { DOC_PURPOSE_CONFIG } from '@/config/statuses'
import type { DataEntry, DocPurpose } from '@/types'

const SOURCE_LABELS: Record<string, string> = {
  upload: 'Загрузка',
  photo: 'Фото',
  manual: 'Ручной',
  api: 'API',
  email: 'Email',
  oneC: '1С',
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  paste: 'Вставка',
}

interface EntryGroup {
  key: string
  label: string
  entries: DataEntry[]
}

export function InboxPage() {
  const navigate = useNavigate()
  const { effectiveCategories } = useCompany()
  const { data: inboxEntries = [], isLoading, isError, refetch } = useInbox()
  const verifyEntry = useVerifyEntry()
  const rejectEntry = useRejectEntry()
  const updateEntry = useUpdateEntry()
  const setDocPurpose = useSetDocPurpose()
  const auditorVerify = useAuditorVerify()

  const [filters, setFilters] = useState<InboxFilters>(defaultInboxFilters)
  const [groupBy, setGroupBy] = useState<GroupBy>('none')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // ---- Фильтрация ----
  const filteredEntries = useMemo(() => {
    return inboxEntries.filter((e) => {
      if (filters.search && !e.title.toLowerCase().includes(filters.search.toLowerCase())) return false
      if (filters.source !== 'all' && e.source !== filters.source) return false
      if (filters.status !== 'all' && e.status !== filters.status) return false
      if (filters.categoryId !== 'all' && e.categoryId !== filters.categoryId) return false
      if (filters.docPurpose !== 'all' && e.docPurpose !== filters.docPurpose) return false
      if (filters.dateFrom && e.createdAt < filters.dateFrom) return false
      if (filters.dateTo && e.createdAt > filters.dateTo + 'T23:59:59') return false
      return true
    })
  }, [inboxEntries, filters])

  // ---- Группировка ----
  const groupedEntries = useMemo((): EntryGroup[] => {
    if (groupBy === 'none') {
      return [{ key: '_all', label: '', entries: filteredEntries }]
    }

    const groups = new Map<string, DataEntry[]>()

    if (groupBy === 'source') {
      for (const e of filteredEntries) {
        const key = e.source
        if (!groups.has(key)) groups.set(key, [])
        groups.get(key)!.push(e)
      }
      return Array.from(groups.entries()).map(([key, entries]) => ({
        key,
        label: SOURCE_LABELS[key] ?? key,
        entries,
      }))
    }

    if (groupBy === 'category') {
      for (const e of filteredEntries) {
        const key = e.categoryId || '_uncategorized'
        if (!groups.has(key)) groups.set(key, [])
        groups.get(key)!.push(e)
      }
      return Array.from(groups.entries()).map(([key, entries]) => ({
        key,
        label: key === '_uncategorized'
          ? 'Без категории'
          : effectiveCategories.find((c) => c.id === key)?.label ?? key,
        entries,
      }))
    }

    if (groupBy === 'date') {
      const now = new Date()
      const today = now.toISOString().slice(0, 10)
      const yesterday = new Date(now.getTime() - 86400000).toISOString().slice(0, 10)
      const weekAgo = new Date(now.getTime() - 7 * 86400000).toISOString().slice(0, 10)

      const dateGroups: Record<string, DataEntry[]> = {
        today: [],
        yesterday: [],
        week: [],
        earlier: [],
      }

      for (const e of filteredEntries) {
        const d = e.createdAt.slice(0, 10)
        if (d === today) dateGroups.today.push(e)
        else if (d === yesterday) dateGroups.yesterday.push(e)
        else if (d >= weekAgo) dateGroups.week.push(e)
        else dateGroups.earlier.push(e)
      }

      const result: EntryGroup[] = []
      if (dateGroups.today.length) result.push({ key: 'today', label: 'Сегодня', entries: dateGroups.today })
      if (dateGroups.yesterday.length) result.push({ key: 'yesterday', label: 'Вчера', entries: dateGroups.yesterday })
      if (dateGroups.week.length) result.push({ key: 'week', label: 'Эта неделя', entries: dateGroups.week })
      if (dateGroups.earlier.length) result.push({ key: 'earlier', label: 'Ранее', entries: dateGroups.earlier })
      return result
    }

    return [{ key: '_all', label: '', entries: filteredEntries }]
  }, [filteredEntries, groupBy, effectiveCategories])

  // ---- Callbacks ----
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

  const handleAuditorVerify = useCallback(
    (id: string) => auditorVerify.mutate(id),
    [auditorVerify],
  )

  const handleCategoryChange = useCallback(
    (id: string, categoryId: string, subcategoryId: string) => {
      updateEntry.mutate({ id, updates: { categoryId, subcategoryId } })
    },
    [updateEntry],
  )

  const handleDocPurposeChange = useCallback(
    (id: string, docPurpose: string) => {
      setDocPurpose.mutate({ id, docPurpose: docPurpose as DataEntry['docPurpose'] })
    },
    [setDocPurpose],
  )

  // ---- Массовые действия ----
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

  const handleBatchAuditorVerify = useCallback(() => {
    for (const id of selectedIds) {
      auditorVerify.mutate(id)
    }
    setSelectedIds(new Set())
  }, [selectedIds, auditorVerify])

  const handleBatchCategory = useCallback(
    (categoryId: string, subcategoryId: string) => {
      for (const id of selectedIds) {
        updateEntry.mutate({ id, updates: { categoryId, subcategoryId } })
      }
      setSelectedIds(new Set())
    },
    [selectedIds, updateEntry],
  )

  const handleBatchDocPurpose = useCallback(
    (docPurpose: DocPurpose) => {
      for (const id of selectedIds) {
        setDocPurpose.mutate({ id, docPurpose })
      }
      setSelectedIds(new Set())
    },
    [selectedIds, setDocPurpose],
  )

  // ---- Рендер ----
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

      {/* Статистика */}
      <InboxStatsBar entries={inboxEntries} />

      {/* Фильтры + группировка */}
      <InboxToolbar
        filters={filters}
        onFiltersChange={setFilters}
        groupBy={groupBy}
        onGroupByChange={setGroupBy}
      />

      {/* Массовые действия */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-lg border bg-card flex-wrap">
          <span className="text-sm text-muted-foreground">
            Выбрано: <span className="font-medium text-foreground">{selectedIds.size}</span>
          </span>

          {/* Назначить категорию */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <FolderOpen className="size-4" />
                Категория
                <ChevronDown className="size-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {effectiveCategories.map((cat) => (
                <DropdownMenuItem
                  key={cat.id}
                  onClick={() => handleBatchCategory(cat.id, cat.subcategories?.[0]?.id ?? '')}
                >
                  {cat.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Назначить назначение */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Target className="size-4" />
                Назначение
                <ChevronDown className="size-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {(Object.entries(DOC_PURPOSE_CONFIG) as [DocPurpose, { label: string }][]).map(([key, cfg]) => (
                <DropdownMenuItem
                  key={key}
                  onClick={() => handleBatchDocPurpose(key)}
                >
                  {cfg.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Проверить аудитором */}
          <Button
            variant="outline"
            size="sm"
            onClick={handleBatchAuditorVerify}
            disabled={auditorVerify.isPending}
            className="text-violet-500 hover:text-violet-400 border-violet-500/30"
          >
            <ShieldCheck className="size-4" />
            {auditorVerify.isPending ? 'Проверка...' : 'Аудитор'}
          </Button>

          {/* Верифицировать (принять) */}
          <Button
            size="sm"
            onClick={handleBatchVerify}
            className="bg-green-600 hover:bg-green-700 text-white"
          >
            <Check className="size-4" />
            Принять
          </Button>

          {/* Отклонить */}
          <Button
            variant="outline"
            size="sm"
            onClick={handleBatchReject}
            className="text-red-500 hover:text-red-400"
          >
            <X className="size-4" />
            Отклонить
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto"
          >
            Снять выделение
          </Button>
        </div>
      )}

      {/* Контент */}
      {filteredEntries.length === 0 && !isLoading ? (
        <EmptyState
          icon={Inbox}
          title="Очередь пуста"
          description="Все записи обработаны. Загрузите новые документы для обработки."
        />
      ) : groupBy === 'none' ? (
        <InboxTable
          entries={filteredEntries}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onRowClick={handleRowClick}
          onVerify={handleVerify}
          onReject={handleReject}
          onAuditorVerify={handleAuditorVerify}
          onCategoryChange={handleCategoryChange}
          onDocPurposeChange={handleDocPurposeChange}
        />
      ) : (
        <div className="space-y-6">
          {groupedEntries.map((group) => (
            <div key={group.key}>
              <h3 className="text-sm font-medium text-muted-foreground mb-2 flex items-center gap-2">
                {group.label}
                <Badge variant="secondary">{group.entries.length}</Badge>
              </h3>
              <InboxTable
                entries={group.entries}
                selectedIds={selectedIds}
                onSelectionChange={setSelectedIds}
                onRowClick={handleRowClick}
                onVerify={handleVerify}
                onReject={handleReject}
                onAuditorVerify={handleAuditorVerify}
                onCategoryChange={handleCategoryChange}
                onDocPurposeChange={handleDocPurposeChange}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
