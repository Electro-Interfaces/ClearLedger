/**
 * React Query хуки для DataEntry — CRUD + workflow.
 * Работают одинаково в API и demo режимах (сервис абстрагирует).
 */

import { useQuery, useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as svc from '@/services/dataEntryService'
import { logEvent } from '@/services/auditService'
import type { DataEntry, FilterState } from '@/types'
import type { EntryStatus } from '@/config/statuses'
import { useMemo, useState, useEffect } from 'react'

// ---- Keys ----

const keys = {
  all: (companyId: string) => ['entries', companyId] as const,
  inbox: (companyId: string) => ['entries', companyId, 'inbox'] as const,
  inboxCount: (companyId: string) => ['entries', companyId, 'inbox-count'] as const,
  detail: (companyId: string, id: string) => ['entries', companyId, id] as const,
  kpi: (companyId: string) => ['entries', companyId, 'kpi'] as const,
}

// ---- Queries ----

/** Все записи текущей компании */
export function useEntries(filters?: Partial<FilterState>) {
  const { companyId } = useCompany()

  const query = useQuery({
    queryKey: [...keys.all(companyId), filters],
    queryFn: () => svc.getEntries(companyId),
  })

  const filtered = useMemo(() => {
    if (!query.data || !filters) return query.data ?? []
    return applyFilters(query.data, filters)
  }, [query.data, filters])

  return { ...query, data: filtered }
}

/** Записи по категории */
export function useEntriesByCategory(categoryId: string, filters?: Partial<FilterState>) {
  const { companyId } = useCompany()

  const query = useQuery({
    queryKey: [...keys.all(companyId), 'category', categoryId, filters],
    queryFn: () => svc.getEntries(companyId),
  })

  const filtered = useMemo(() => {
    if (!query.data) return []
    let result = query.data.filter((e) => e.categoryId === categoryId)
    if (filters) result = applyFilters(result, filters)
    return result
  }, [query.data, categoryId, filters])

  return { ...query, data: filtered }
}

/** Inbox: status = new | recognized */
export function useInbox() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.inbox(companyId),
    queryFn: () => svc.getInboxEntries(companyId),
  })
}

/** Количество записей в inbox (для бейджа) */
export function useInboxCount() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.inboxCount(companyId),
    queryFn: () => svc.getInboxCount(companyId),
  })
}

/** Одна запись по ID */
export function useEntry(id: string) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.detail(companyId, id),
    queryFn: () => svc.getEntry(companyId, id),
    enabled: !!id,
  })
}

/** KPI */
export function useKpi() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.kpi(companyId),
    queryFn: () => svc.computeKpi(companyId),
  })
}

// ---- Mutations ----

export function useCreateEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Omit<svc.CreateEntryInput, 'companyId'>) =>
      svc.createEntry({ ...input, companyId }),
    onSuccess: (entry) => {
      logEvent({ companyId, entryId: entry.id, action: 'created', details: entry.title })
      invalidateAll(qc, companyId)
    },
  })
}

export function useUpdateEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: Partial<DataEntry> }) =>
      svc.updateEntry(companyId, id, updates),
    onSuccess: (_data, vars) => {
      logEvent({ companyId, entryId: vars.id, action: 'updated', details: vars.id })
      invalidateAll(qc, companyId)
    },
  })
}

export function useDeleteEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.deleteEntry(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useVerifyEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.verifyEntry(companyId, id),
    onSuccess: (entry, id) => {
      logEvent({ companyId, entryId: id, action: 'verified', details: entry?.title })
      invalidateAll(qc, companyId)
    },
  })
}

export function useRejectEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      svc.rejectEntry(companyId, id, reason),
    onSuccess: (_data, vars) => {
      logEvent({ companyId, entryId: vars.id, action: 'rejected', details: vars.reason })
      invalidateAll(qc, companyId)
    },
  })
}

export function useTransferEntries() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => svc.transferEntries(companyId, ids),
    onSuccess: (count, ids) => {
      logEvent({ companyId, action: 'transferred', details: `${count} из ${ids.length}` })
      invalidateAll(qc, companyId)
    },
  })
}

export function useArchiveEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.archiveEntry(companyId, id),
    onSuccess: (_data, id) => {
      logEvent({ companyId, entryId: id, action: 'archived', details: id })
      invalidateAll(qc, companyId)
    },
  })
}

export function useRestoreEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.restoreEntry(companyId, id),
    onSuccess: (_data, id) => {
      logEvent({ companyId, entryId: id, action: 'restored', details: id })
      invalidateAll(qc, companyId)
    },
  })
}

export function useExcludeEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.excludeEntry(companyId, id),
    onSuccess: (_data, id) => {
      logEvent({ companyId, entryId: id, action: 'excluded', details: id })
      invalidateAll(qc, companyId)
    },
  })
}

export function useIncludeEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.includeEntry(companyId, id),
    onSuccess: (_data, id) => {
      logEvent({ companyId, entryId: id, action: 'included', details: id })
      invalidateAll(qc, companyId)
    },
  })
}

// ---- Paginated (infinite scroll / load more) ----

/** Пагинированные записи с "Загрузить ещё" */
export function useInfiniteEntries(params?: { status?: string; categoryId?: string; search?: string; pageSize?: number }) {
  const { companyId } = useCompany()
  const pageSize = params?.pageSize ?? 50

  return useInfiniteQuery({
    queryKey: ['entries', companyId, 'paginated', params],
    queryFn: ({ pageParam = 0 }) =>
      svc.getEntriesPaginated(companyId, {
        offset: pageParam as number,
        limit: pageSize,
        status: params?.status,
        categoryId: params?.categoryId,
        search: params?.search,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, _allPages, lastPageParam) => {
      if (!lastPage.hasMore) return undefined
      return (lastPageParam as number) + pageSize
    },
  })
}

// ---- Search ----

/** Поиск с debounce */
export function useSearchEntries(query: string, debounceMs = 300) {
  const { companyId } = useCompany()
  const [debouncedQuery, setDebouncedQuery] = useState(query)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), debounceMs)
    return () => clearTimeout(timer)
  }, [query, debounceMs])

  return useQuery({
    queryKey: [...keys.all(companyId), 'search', debouncedQuery],
    queryFn: () => svc.searchEntries(companyId, debouncedQuery),
    enabled: debouncedQuery.length >= 2,
  })
}

// ---- Category Stats ----

/** Распределение записей по категориям (для CategoryChart) */
export function useCategoryStats() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: [...keys.all(companyId), 'category-stats'],
    queryFn: () => svc.computeCategoryStats(companyId),
  })
}

// ---- Utils ----

function invalidateAll(qc: ReturnType<typeof useQueryClient>, companyId: string) {
  qc.invalidateQueries({ queryKey: ['entries', companyId] })
}

function applyFilters(entries: DataEntry[], filters: Partial<FilterState>): DataEntry[] {
  return entries.filter((e) => {
    // По умолчанию скрываем archived
    if (!filters.showArchived && e.status === 'archived') return false
    // По умолчанию скрываем excluded
    if (!filters.showExcluded && e.metadata._excluded === 'true') return false
    // По умолчанию показываем только последние версии
    if (!filters.showAllVersions && e.metadata._isLatestVersion === 'false') return false
    if (filters.search && !e.title.toLowerCase().includes(filters.search.toLowerCase())) return false
    if (filters.status && filters.status !== 'all' && e.status !== (filters.status as EntryStatus)) return false
    if (filters.source && filters.source !== 'all' && e.source !== filters.source) return false
    if (filters.subcategory && filters.subcategory !== 'all' && e.subcategoryId !== filters.subcategory) return false
    if (filters.dateFrom && e.createdAt < filters.dateFrom) return false
    if (filters.dateTo && e.createdAt > filters.dateTo) return false
    return true
  })
}
