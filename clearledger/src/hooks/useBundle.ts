/**
 * React Query хуки для бизнес-комплектов документов.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import * as bundleSvc from '@/services/bundleService'
import { toast } from 'sonner'
import type { DataEntry } from '@/types'

// ---- Keys ----

const keys = {
  all: (companyId: string) => ['bundle', companyId] as const,
  tree: (companyId: string, entryId: string) => ['bundle', companyId, 'tree', entryId] as const,
  allTrees: (companyId: string) => ['bundle', companyId, 'all-trees'] as const,
  suggestions: (companyId: string, entryId: string) => ['bundle', companyId, 'suggestions', entryId] as const,
}

// ---- Queries ----

/** Дерево комплекта для записи */
export function useBundleTree(entryId: string) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.tree(companyId, entryId),
    queryFn: () => bundleSvc.getBundleTree(companyId, entryId),
    enabled: !!entryId,
    staleTime: 30_000,
  })
}

/** Все деревья комплектов + одиночные документы */
export function useAllBundleTrees(entries: DataEntry[]) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: [...keys.allTrees(companyId), entries.length],
    queryFn: () => bundleSvc.getAllBundleTrees(companyId, entries),
    enabled: entries.length > 0,
    staleTime: 30_000,
  })
}

/** Авто-предложения кандидатов в комплект */
export function useBundleSuggestions(entryId: string, enabled = true) {
  const { companyId } = useCompany()
  return useQuery({
    queryKey: keys.suggestions(companyId, entryId),
    queryFn: () => bundleSvc.suggestBundleMembers(companyId, entryId),
    enabled: !!entryId && enabled,
    staleTime: 30_000,
  })
}

// ---- Mutations ----

/** Создать комплект (документ → корень) */
export function useCreateBundle() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ rootEntryId }: { rootEntryId: string }) =>
      bundleSvc.createBundle(companyId, rootEntryId),
    onSuccess: () => {
      toast.success('Комплект создан')
      invalidateBundle(qc, companyId)
    },
    onError: () => toast.error('Ошибка создания комплекта'),
  })
}

/** Добавить в комплект как подчинённый (с валидацией) */
export function useAddToBundle() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ parentId, childId }: { parentId: string; childId: string }) =>
      bundleSvc.addToBundle(companyId, parentId, childId),
    onSuccess: (result) => {
      if (!result.allowed) {
        toast.error(result.reason ?? 'Нельзя добавить этот документ')
      } else {
        toast.success('Документ добавлен в комплект')
      }
      invalidateBundle(qc, companyId)
    },
    onError: () => toast.error('Ошибка добавления в комплект'),
  })
}

/** Убрать из комплекта */
export function useRemoveFromBundle() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (entryId: string) => bundleSvc.removeFromBundle(companyId, entryId),
    onSuccess: () => {
      toast.success('Убрано из комплекта')
      invalidateBundle(qc, companyId)
    },
    onError: () => toast.error('Ошибка удаления из комплекта'),
  })
}

/** Переместить к другому родителю (с валидацией) */
export function useReparent() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId, newParentId }: { entryId: string; newParentId: string }) =>
      bundleSvc.reparent(companyId, entryId, newParentId),
    onSuccess: (result) => {
      if (!result.allowed) {
        toast.error(result.reason ?? 'Нельзя переместить этот документ')
      } else {
        toast.success('Документ перемещён')
      }
      invalidateBundle(qc, companyId)
    },
    onError: () => toast.error('Ошибка перемещения'),
  })
}

// ---- Utils ----

function invalidateBundle(qc: ReturnType<typeof useQueryClient>, companyId: string) {
  qc.invalidateQueries({ queryKey: ['bundle', companyId] })
  qc.invalidateQueries({ queryKey: ['entries', companyId] })
}
