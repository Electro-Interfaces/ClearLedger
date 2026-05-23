/**
 * React Query хуки для справочников НСИ.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as ref from '@/services/referenceService'
import type { Counterparty, Organization, Nomenclature, Contract } from '@/types'

// ---- Keys ----

const keys = {
  counterparties: (companyId: string) => ['references', companyId, 'counterparties'] as const,
  organizations: (companyId: string) => ['references', companyId, 'organizations'] as const,
  nomenclature: (companyId: string) => ['references', companyId, 'nomenclature'] as const,
  contracts: (companyId: string) => ['references', companyId, 'contracts'] as const,
  warehouses: (companyId: string) => ['references', companyId, 'warehouses'] as const,
  bankAccounts: (companyId: string) => ['references', companyId, 'bankAccounts'] as const,
  stats: (companyId: string) => ['references', companyId, 'stats'] as const,
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>, companyId: string) {
  qc.invalidateQueries({ queryKey: ['references', companyId] })
}

// ============================================================
// Counterparties
// ============================================================

export function useCounterparties() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.counterparties(companyId),
    queryFn: () => ref.getCounterparties(companyId),
  })
}

export function useCreateCounterparty() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Omit<Counterparty, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>) =>
      ref.createCounterparty(companyId, input),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useUpdateCounterparty() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: Partial<Counterparty> }) =>
      ref.updateCounterparty(companyId, id, updates),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useDeleteCounterparty() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => ref.deleteCounterparty(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useMergeCounterparties() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ keepId, removeId }: { keepId: string; removeId: string }) =>
      ref.mergeCounterparties(companyId, keepId, removeId),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ============================================================
// Organizations
// ============================================================

export function useOrganizations() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.organizations(companyId),
    queryFn: () => ref.getOrganizations(companyId),
  })
}

export function useCreateOrganization() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Omit<Organization, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>) =>
      ref.createOrganization(companyId, input),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useDeleteOrganization() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => ref.deleteOrganization(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ============================================================
// Nomenclature
// ============================================================

export function useNomenclature() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.nomenclature(companyId),
    queryFn: () => ref.getNomenclature(companyId),
  })
}

export function useCreateNomenclature() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Omit<Nomenclature, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>) =>
      ref.createNomenclature(companyId, input),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useDeleteNomenclature() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => ref.deleteNomenclature(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ============================================================
// Contracts
// ============================================================

export function useContracts() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.contracts(companyId),
    queryFn: () => ref.getContracts(companyId),
  })
}

export function useCreateContract() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Omit<Contract, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>) =>
      ref.createContract(companyId, input),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

export function useDeleteContract() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => ref.deleteContract(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ============================================================
// Warehouses
// ============================================================

export function useWarehouses() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.warehouses(companyId),
    queryFn: () => ref.getWarehouses(companyId),
  })
}

export function useDeleteWarehouse() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => ref.deleteWarehouse(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ============================================================
// BankAccounts
// ============================================================

export function useBankAccounts() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.bankAccounts(companyId),
    queryFn: () => ref.getBankAccounts(companyId),
  })
}

export function useDeleteBankAccount() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => ref.deleteBankAccount(companyId, id),
    onSuccess: () => invalidateAll(qc, companyId),
  })
}

// ============================================================
// Stats
// ============================================================

export function useReferenceStats() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.stats(companyId),
    queryFn: () => ref.getReferenceStats(companyId),
  })
}
