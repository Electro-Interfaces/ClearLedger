/**
 * React Query хуки для аудит-лога.
 */

import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { getEvents, getEventsForEntry } from '@/services/auditService'
import type { AuditFilters } from '@/services/auditService'

/** Все события компании с фильтрацией */
export function useAuditEvents(filters?: AuditFilters) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['audit', companyId, filters],
    queryFn: () => getEvents(companyId, filters),
  })
}

/** События конкретной записи */
export function useEntryAudit(entryId: string) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['audit', companyId, entryId],
    queryFn: () => getEventsForEntry(companyId, entryId),
    enabled: !!entryId,
  })
}
