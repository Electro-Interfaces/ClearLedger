/**
 * Построение виртуальной файловой системы «Документы» из каталога компании.
 *
 * Источник — хранилище загруженных документов (`getAllLoadedDocs`): у каждого
 * документа готовый путь `catalog` (напр. `/Нефтепродукты АЗС/Смены/{станция}/
 * {год}-{месяц}/`). Дерево строится РОВНО по этим путям — папки = сегменты пути,
 * листья = документы. Так раздел показывает каталог компании один-в-один.
 */

import { useMemo, useCallback, useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useFilters } from '@/contexts/FilterContext'
import { getAllLoadedDocs, type LoadedDocument } from '@/services/channelSyncService'
import { format } from 'date-fns'
import type { ShiftRecord } from '@/services/fuel/types'
import type { FsNode, RawPanelFilters, SortConfig } from './raw-panel-types'

function safeFmt(iso: string | undefined, withTime = true): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return format(d, withTime ? 'dd.MM.yyyy HH:mm' : 'dd.MM.yyyy')
}

/** Иконочный тип узла по backend-типу документа. */
function iconType(docType: string): FsNode['docType'] {
  if (docType === 'shift_report') return 'shift'
  if (docType === 'delivery' || docType === 'receipt') return 'delivery'
  return undefined
}

/** Человекочитаемый тип документа (колонка «Тип», как в проводнике). */
export function docTypeLabel(docType: string): string {
  const map: Record<string, string> = {
    shift_report: 'Сменный отчёт',
    receipt: 'Поступление (ТТН)',
    delivery: 'Поступление (ТТН)',
    price: 'Цены',
    sts_transactions: 'Операции отпуска',
    sts_coupons: 'Купоны/талоны',
    sts_tanks: 'Остатки резервуаров',
    msto_transactions: 'Онлайн-заказы',
    corp_transactions: 'Корп. карты',
  }
  return map[docType] ?? 'Документ'
}

export function useRawPanelTree(filters: RawPanelFilters, sortConfig: SortConfig) {
  const queryClient = useQueryClient()
  const { stationCode } = useFilters()

  const [docs, setDocs] = useState<LoadedDocument[]>(() => getAllLoadedDocs())
  const [dataUpdatedAt, setDataUpdatedAt] = useState<number>(() => Date.now())

  // Перечитать хранилище при монтировании (данные могли пополниться в др. разделе).
  useEffect(() => {
    setDocs(getAllLoadedDocs())
    setDataUpdatedAt(Date.now())
  }, [])

  const fsTree = useMemo(() => {
    const tree = new Map<string, FsNode[]>()

    // ── фильтрация документов ──
    let filtered = docs
    if (stationCode !== 'all') {
      const code = Number(stationCode)
      filtered = filtered.filter((d) => d.stationId === code)
    }
    if (filters.docType === 'shifts') filtered = filtered.filter((d) => d.docType === 'shift_report')
    if (filters.docType === 'receipts') filtered = filtered.filter((d) => d.docType === 'delivery' || d.docType === 'receipt')
    if (filters.status === 'open') filtered = filtered.filter((d) => (d.data as ShiftRecord)?.status !== 'closed')
    if (filters.status === 'closed') filtered = filtered.filter((d) => (d.data as ShiftRecord)?.status === 'closed')
    const q = filters.searchQuery.trim().toLowerCase()
    if (q) filtered = filtered.filter((d) => d.title.toLowerCase().includes(q) || d.catalog.toLowerCase().includes(q))

    // ── построение дерева по catalog-путям ──
    const ensureFolder = (parentKey: string, name: string, path: string) => {
      const siblings = tree.get(parentKey) ?? []
      if (!siblings.some((n) => n.type === 'folder' && n.path === path)) {
        siblings.push({ name, type: 'folder', path, childCount: 0 })
        tree.set(parentKey, siblings)
      }
    }

    for (const doc of filtered) {
      const segs = doc.catalog.split('/').map((s) => s.trim()).filter(Boolean)
      let parentKey = ''
      let pathAcc = ''
      for (const seg of segs) {
        pathAcc = pathAcc ? `${pathAcc}/${seg}` : seg
        ensureFolder(parentKey, seg, pathAcc)
        parentKey = pathAcc
      }
      // Лист-документ в конечной папке. path уникален по id документа.
      const shiftData = doc.data as ShiftRecord | undefined
      const fileNode: FsNode = {
        name: doc.title || 'Документ',
        type: 'file',
        path: `${parentKey}/#${doc.id}`,
        doc,
        stationId: doc.stationId,
        docType: iconType(doc.docType),
        date: safeFmt(doc.date || doc.loadedAt),
        status: doc.docType === 'shift_report' ? (shiftData?.status === 'closed' ? 'Закрыта' : 'Открыта') : undefined,
        size: '—',
      }
      const files = tree.get(parentKey) ?? []
      files.push(fileNode)
      tree.set(parentKey, files)
    }

    // childCount = число прямых детей каждой папки (как в проводнике).
    for (const [, nodes] of tree) {
      for (const n of nodes) {
        if (n.type === 'folder') n.childCount = (tree.get(n.path) ?? []).length
      }
    }

    return tree
  }, [docs, stationCode, filters])

  // Плоский отсортированный список файлов (вид «Список»/«Таблица»).
  const flatFiles = useMemo(() => {
    const files: FsNode[] = []
    for (const [, nodes] of fsTree) {
      for (const node of nodes) if (node.type === 'file') files.push(node)
    }
    files.sort((a, b) => {
      const dir = sortConfig.direction === 'asc' ? 1 : -1
      switch (sortConfig.column) {
        case 'name':
          return dir * a.name.localeCompare(b.name, 'ru')
        case 'date': {
          const da = a.doc?.date || a.doc?.loadedAt || ''
          const db = b.doc?.date || b.doc?.loadedAt || ''
          return dir * da.localeCompare(db)
        }
        case 'status':
          return dir * (a.status || '').localeCompare(b.status || '')
        default:
          return 0
      }
    })
    return files
  }, [fsTree, sortConfig])

  const totalItemCount = useMemo(() => flatFiles.length, [flatFiles])

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-all-receipts'] })
    setDocs(getAllLoadedDocs())
    setDataUpdatedAt(Date.now())
  }, [queryClient])

  return {
    fsTree,
    flatFiles,
    isLoading: false,
    isFetching: false,
    totalItemCount,
    dataUpdatedAt,
    handleRefresh,
  }
}

/** Build flat list of visible nodes from tree + expandedPaths */
export function buildVisibleList(
  fsTree: Map<string, FsNode[]>,
  expandedPaths: string[],
): { node: FsNode; depth: number }[] {
  const result: { node: FsNode; depth: number }[] = []

  function walk(parentKey: string, depth: number) {
    const nodes = fsTree.get(parentKey)
    if (!nodes) return
    for (const node of nodes) {
      result.push({ node, depth })
      if (node.type === 'folder' && expandedPaths.includes(node.path)) {
        walk(node.path, depth + 1)
      }
    }
  }

  walk('', 0)
  return result
}
