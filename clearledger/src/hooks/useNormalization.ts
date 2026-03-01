/**
 * React Query хуки для нормализации (Layer 2 pipeline).
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as normService from '@/services/normalizationService'
import type { AuditMissingEntry } from '@/types'
import type { ProfileId } from '@/config/profiles'

const keys = {
  summary: (companyId: string) => ['normalization', companyId, 'summary'] as const,
  state: (companyId: string) => ['normalization', companyId, 'state'] as const,
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>, companyId: string) {
  qc.invalidateQueries({ queryKey: ['normalization', companyId] })
  qc.invalidateQueries({ queryKey: ['entries', companyId] })
}

export function useNormalizationSummary() {
  const { company, companyId } = useCompany()
  return useQuery({
    queryKey: keys.summary(companyId),
    queryFn: () => normService.getNormalizationSummary(companyId, company.profileId as ProfileId),
    staleTime: 30_000,
  })
}

export function useNormalizationState() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.state(companyId),
    queryFn: () => normService.getNormalizationState(companyId),
  })
}

export function useRunNormalizationPipeline() {
  const { company, companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (onProgress?: (phase: string, done: number, total: number) => void) =>
      normService.runNormalizationPipeline(companyId, company.profileId as ProfileId, onProgress),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useApplyEnrichment() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId, enrichment }: { entryId: string; enrichment: Record<string, string> }) =>
      normService.applyEnrichment(companyId, entryId, enrichment),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useApplyAuditEnrichment() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId, metadataKey, proposedValue }: { entryId: string; metadataKey: string; proposedValue: string }) =>
      normService.applyAuditEnrichment(companyId, entryId, metadataKey, proposedValue),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useCreateEntryFromAudit() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (proposal: AuditMissingEntry) =>
      normService.createEntryFromAuditProposal(companyId, proposal),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['entries', companyId] })
    },
  })
}
