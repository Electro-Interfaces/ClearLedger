/**
 * React Query хуки для учётных документов 1С и сверки.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as accService from '@/services/accountingDocService'
import { notifyReconciliation } from '@/services/notificationService'
import type { AccountingDocType, MatchStatus } from '@/types'

// ---- Keys ----

const keys = {
  docs: (companyId: string) => ['accountingDocs', companyId] as const,
  doc: (companyId: string, id: string) => ['accountingDocs', companyId, id] as const,
  summary: (companyId: string) => ['reconciliation', companyId, 'summary'] as const,
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>, companyId: string) {
  qc.invalidateQueries({ queryKey: ['accountingDocs', companyId] })
  qc.invalidateQueries({ queryKey: ['reconciliation', companyId] })
}

// ============================================================
// Accounting Docs
// ============================================================

export function useAccountingDocs(filters?: {
  docType?: AccountingDocType
  counterparty?: string
  dateFrom?: string
  dateTo?: string
  matchStatus?: MatchStatus
}) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: [...keys.docs(companyId), filters],
    queryFn: () => accService.getAccountingDocs(companyId, filters),
  })
}

export function useDeleteAccountingDoc() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => accService.deleteAccountingDoc(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useImportAccountingDocs() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (docs: Parameters<typeof accService.importAccountingDocs>[1]) =>
      accService.importAccountingDocs(companyId, docs),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ============================================================
// Reconciliation
// ============================================================

export function useReconciliationSummary() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.summary(companyId),
    queryFn: () => accService.getReconciliationSummary(companyId),
  })
}

export function useRunReconciliation() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => accService.runReconciliation(companyId),
    onSuccess: (result) => {
      invalidateAll(qc, companyId)
      qc.invalidateQueries({ queryKey: ['notifications'] })
      notifyReconciliation(result.matched, result.unmatched)
    },
  })
}

export function useManualMatch() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ docId, entryId }: { docId: string; entryId: string }) =>
      accService.manualMatch(companyId, docId, entryId),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useUnmatch() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (docId: string) => accService.unmatch(companyId, docId),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}
