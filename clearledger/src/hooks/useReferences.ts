/**
 * React Query хуки для справочников НСИ.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as ref from '@/services/referenceService'
import type { Counterparty, Organization, Nomenclature, Contract, ContractScopeType } from '@/types'

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
// Ось договор↔точки (Фаза 2)
// ============================================================

/** Установить охват договора (company/locations/unassigned + точки). */
export function useSetContractScope() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { contractId: string; scopeType: ContractScopeType; locationIds?: string[] }) =>
      ref.setContractScope(v.contractId, v.scopeType, v.locationIds ?? []),
    onSuccess: (_d, v) => {
      invalidateAll(qc, companyId)
      qc.invalidateQueries({ queryKey: ['axis', 'contract', v.contractId, 'locations'] })
      qc.invalidateQueries({ queryKey: ['axis'] })  // карточки контрагента/точки
    },
  })
}

/** Точки конкретного договора. */
export function useContractLocations(contractId: string | null) {
  return useQuery({
    queryKey: ['axis', 'contract', contractId, 'locations'],
    queryFn: () => ref.getContractLocations(contractId!),
    enabled: !!contractId,
  })
}

/** Где работает контрагент (агрегат). */
export function useCounterpartyLocations(counterpartyId: string | null) {
  return useQuery({
    queryKey: ['axis', 'counterparty', counterpartyId, 'locations'],
    queryFn: () => ref.getCounterpartyLocations(counterpartyId!),
    enabled: !!counterpartyId,
  })
}

/** Договоры точки. */
export function useLocationContracts(locationId: string | null) {
  return useQuery({
    queryKey: ['axis', 'location', locationId, 'contracts'],
    queryFn: () => ref.getLocationContracts(locationId!),
    enabled: !!locationId,
  })
}

/** Активность контрагента в учёте (fuel/ГИГ: документы БП по ИНН). */
export function useCounterpartyActivity(counterpartyId: string | null) {
  return useQuery({
    queryKey: ['axis', 'counterparty', counterpartyId, 'activity'],
    queryFn: () => ref.getCounterpartyActivity(counterpartyId!),
    enabled: !!counterpartyId,
    staleTime: 60_000,
  })
}

/** Платёжная дисциплина станции (энергоснабжение/аренда, статусы оплат). */
export function useLocationSettlements(locationId: string | null) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'location', locationId, 'settlements', companyId],
    queryFn: () => ref.getLocationSettlements(companyId, locationId!),
    enabled: !!locationId && !!companyId,
  })
}

/** Все записи платёжной дисциплины компании (индикаторы в списке/карте ЭЗС). */
export function useAllSettlements() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'settlements', companyId],
    queryFn: () => ref.getAllSettlements(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
}

/** Агрегат платёжной дисциплины (витрины «Дебиторка»/«Энергозакупка»). */
export function usePaymentDisciplineSummary() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'payment-summary', companyId],
    queryFn: () => ref.getPaymentDisciplineSummary(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
}

/** Детализация платёжной дисциплины (строки таблицы) по роли energy|rent|service. */
export function useSettlementsDetail(role?: 'energy' | 'rent' | 'service') {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'settlements-detail', companyId, role ?? 'all'],
    queryFn: () => ref.getSettlementsDetail(companyId, role),
    enabled: !!companyId,
    staleTime: 60_000,
  })
}

/** Модель нормализации канала реестров (потоки → сопряжение → L2-сущности). */
export function useReestrModel() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'reestr-model', companyId],
    queryFn: () => ref.getReestrModel(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
}

/** Сверка отпуска: сводная выработка (слот obshaya) ↔ зарядные сессии. */
export function useDispenseRecon() {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'dispense-recon', companyId],
    queryFn: () => ref.getDispenseRecon(companyId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
}

/** Входящая э/э по месяцам (объёмы/тарифы/стоимость) — витрина «Энергозакупка». */
export function useEnergyPeriodsSummary(months = 24) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'energy-periods', companyId, months],
    queryFn: () => ref.getEnergyPeriodsSummary(companyId, months),
    enabled: !!companyId,
    staleTime: 60_000,
  })
}

/** Грани договора по разрезам (номенклатура/каналы/…). */
export function useContractDimensions(contractId: string | null) {
  return useQuery({
    queryKey: ['axis', 'contract', contractId, 'dimensions'],
    queryFn: () => ref.getContractDimensions(contractId!),
    enabled: !!contractId,
  })
}

export function useSetContractDimension() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { contractId: string; dimType: string; refs: string[] }) =>
      ref.setContractDimension(v.contractId, v.dimType, v.refs),
    onSuccess: (_d, v) =>
      qc.invalidateQueries({ queryKey: ['axis', 'contract', v.contractId, 'dimensions'] }),
  })
}

/** Обратная навигация: договоры по элементу разреза (грань→договоры). */
export function useDimensionContracts(dimType: string, dimRef: string | null) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: ['axis', 'dimension', dimType, dimRef, 'contracts'],
    queryFn: () => ref.getDimensionContracts(companyId, dimType, dimRef!),
    enabled: !!dimRef,
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
