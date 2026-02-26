/**
 * React Query хуки для коннекторов — CRUD в localStorage.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as svc from '@/services/connectorService'
import type { Connector } from '@/types'

const keys = {
  all: (companyId: string) => ['connectors', companyId] as const,
  detail: (companyId: string, id: string) => ['connectors', companyId, id] as const,
}

export function useConnectors() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.all(companyId),
    queryFn: () => svc.getConnectors(companyId),
  })
}

export function useConnector(id: string) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.detail(companyId, id),
    queryFn: () => svc.getConnector(companyId, id),
    enabled: !!id,
  })
}

export function useCreateConnector() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Omit<svc.CreateConnectorInput, 'companyId'>) =>
      Promise.resolve(svc.createConnector({ ...input, companyId })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors', companyId] }),
  })
}

export function useUpdateConnector() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: Partial<Connector> }) =>
      Promise.resolve(svc.updateConnector(companyId, id, updates)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors', companyId] }),
  })
}

export function useDeleteConnector() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => Promise.resolve(svc.deleteConnector(companyId, id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connectors', companyId] }),
  })
}

export function useSyncConnector() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (connectorId: string) => Promise.resolve(svc.simulateSync(companyId, connectorId)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connectors', companyId] })
      qc.invalidateQueries({ queryKey: ['entries'] })
    },
  })
}
