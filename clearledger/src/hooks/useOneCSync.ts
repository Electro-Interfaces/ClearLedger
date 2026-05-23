/**
 * React Query хуки для интеграции 1С.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as svc from '@/services/oneCIntegrationService'
import type { CreateConnectionInput, UpdateConnectionInput } from '@/services/oneCIntegrationService'

const keys = {
  connections: (companyId: string) => ['onec-connections', companyId] as const,
  connection: (id: string) => ['onec-connection', id] as const,
  syncStatus: (id: string) => ['onec-sync-status', id] as const,
  syncHistory: (id: string) => ['onec-sync-history', id] as const,
}

// ── Подключения ─────────────────────────────────────────

export function useOneCConnections() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.connections(companyId),
    queryFn: () => svc.getConnections(companyId),
  })
}

export function useOneCConnection(id: string) {
  return useQuery({
    queryKey: keys.connection(id),
    queryFn: () => svc.getConnection(id),
    enabled: !!id,
  })
}

export function useCreateOneCConnection() {
  const qc = useQueryClient()
  const { companyId } = useCompany()
  return useMutation({
    mutationFn: (input: CreateConnectionInput) => svc.createConnection(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.connections(companyId) })
    },
  })
}

export function useUpdateOneCConnection() {
  const qc = useQueryClient()
  const { companyId } = useCompany()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateConnectionInput }) =>
      svc.updateConnection(id, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.connections(companyId) })
    },
  })
}

export function useDeleteOneCConnection() {
  const qc = useQueryClient()
  const { companyId } = useCompany()
  return useMutation({
    mutationFn: (id: string) => svc.deleteConnection(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.connections(companyId) })
    },
  })
}

// ── Тест подключения ────────────────────────────────────

export function useTestOneCConnection() {
  return useMutation({
    mutationFn: (id: string) => svc.testConnection(id),
  })
}

// ── Синхронизация ───────────────────────────────────────

export function useSyncCatalogs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.syncCatalogs(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: keys.syncStatus(id) })
      qc.invalidateQueries({ queryKey: keys.syncHistory(id) })
    },
  })
}

export function useSyncDocuments() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.syncDocuments(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: keys.syncStatus(id) })
      qc.invalidateQueries({ queryKey: keys.syncHistory(id) })
    },
  })
}

export function useSyncFull() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.syncFull(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: keys.syncStatus(id) })
      qc.invalidateQueries({ queryKey: keys.syncHistory(id) })
      qc.invalidateQueries({ queryKey: ['entries'] })
    },
  })
}

// ── Статус и история ────────────────────────────────────

export function useSyncStatus(connectionId: string) {
  return useQuery({
    queryKey: keys.syncStatus(connectionId),
    queryFn: () => svc.getSyncStatus(connectionId),
    enabled: !!connectionId,
    refetchInterval: 5000, // polling при running
  })
}

export function useSyncHistory(connectionId: string) {
  return useQuery({
    queryKey: keys.syncHistory(connectionId),
    queryFn: () => svc.getSyncHistory(connectionId),
    enabled: !!connectionId,
  })
}

// ── Экспорт ─────────────────────────────────────────────

export function useExportTo1C() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => svc.exportTo1C(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: keys.syncHistory(id) })
    },
  })
}

export function useExportStatus(connectionId: string) {
  return useQuery({
    queryKey: ['onec-export-status', connectionId],
    queryFn: () => svc.getExportStatus(connectionId),
    enabled: !!connectionId,
  })
}
