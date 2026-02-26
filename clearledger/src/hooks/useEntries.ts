/**
 * React Query хуки для DataEntry — CRUD + workflow.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as svc from '@/services/dataEntryService'
import type { DataEntry, FilterState } from '@/types'
import type { EntryStatus } from '@/config/statuses'
import { useMemo } from 'react'

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
      Promise.resolve(svc.createEntry({ ...input, companyId })),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useUpdateEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: Partial<DataEntry> }) =>
      Promise.resolve(svc.updateEntry(companyId, id, updates)),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useDeleteEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => Promise.resolve(svc.deleteEntry(companyId, id)),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useVerifyEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => Promise.resolve(svc.verifyEntry(companyId, id)),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useRejectEntry() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      Promise.resolve(svc.rejectEntry(companyId, id, reason)),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useTransferEntries() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => Promise.resolve(svc.transferEntries(companyId, ids)),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ---- Utils ----

function invalidateAll(qc: ReturnType<typeof useQueryClient>, companyId: string) {
  qc.invalidateQueries({ queryKey: ['entries', companyId] })
}

function applyFilters(entries: DataEntry[], filters: Partial<FilterState>): DataEntry[] {
  return entries.filter((e) => {
    if (filters.search && !e.title.toLowerCase().includes(filters.search.toLowerCase())) return false
    if (filters.status && filters.status !== 'all' && e.status !== (filters.status as EntryStatus)) return false
    if (filters.source && filters.source !== 'all' && e.source !== filters.source) return false
    if (filters.subcategory && filters.subcategory !== 'all' && e.subcategoryId !== filters.subcategory) return false
    if (filters.dateFrom && e.createdAt < filters.dateFrom) return false
    if (filters.dateTo && e.createdAt > filters.dateTo) return false
    return true
  })
}
