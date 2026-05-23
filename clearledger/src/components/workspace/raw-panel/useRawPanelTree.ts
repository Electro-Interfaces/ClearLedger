import { useMemo, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useShifts, useAllReceipts } from '@/hooks/useFuel'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getSettings } from '@/services/settingsService'
import { format } from 'date-fns'
import type { StsShift } from '@/services/fuel/types'
import type { FsNode, RawPanelFilters, SortConfig } from './raw-panel-types'
import { MONTH_NAMES } from './raw-panel-constants'

export function useRawPanelTree(filters: RawPanelFilters, sortConfig: SortConfig) {
  const settings = getSettings()
  const queryClient = useQueryClient()
  const { globalStation } = useWorkspace()
  const filterStation = globalStation === 'all' ? undefined : Number(globalStation)
  const { data: shifts, isLoading, isFetching, dataUpdatedAt } = useShifts(filterStation)
  const { data: allReceipts } = useAllReceipts(filterStation)

  const stId = filterStation ?? settings.stations[0]?.code ?? 0

  // Build virtual filesystem tree
  const fsTree = useMemo(() => {
    if (!shifts) return new Map<string, FsNode[]>()

    const tree = new Map<string, FsNode[]>()
    const rootNodes: FsNode[] = []
    const stationCodes = new Set<number>()
    stationCodes.add(stId)

    // Filter shifts
    let filtered = shifts
    if (filters.status === 'open') filtered = filtered.filter((s) => !s.dt_close)
    if (filters.status === 'closed') filtered = filtered.filter((s) => !!s.dt_close)
    if (filters.searchQuery.trim()) {
      const q = filters.searchQuery.toLowerCase()
      filtered = filtered.filter((s) =>
        String(s.shift).includes(q) ||
        (s.dt_open && format(new Date(s.dt_open), 'dd.MM.yyyy').includes(q)),
      )
    }

    // Group by year/month
    const byYearMonth = new Map<string, StsShift[]>()
    for (const s of filtered) {
      const d = s.dt_open ? new Date(s.dt_open) : null
      const year = d ? String(d.getFullYear()) : '—'
      const month = d ? String(d.getMonth() + 1).padStart(2, '0') : '00'
      const key = `${year}/${month}`
      if (!byYearMonth.has(key)) byYearMonth.set(key, [])
      byYearMonth.get(key)!.push(s)
    }

    for (const code of stationCodes) {
      const sName = settings.stations.find((st) => st.code === code)?.name ?? `АЗС-${code}`
      rootNodes.push({ name: sName, type: 'folder', path: sName, childCount: 0 })

      const years = new Set<string>()
      for (const [ym] of byYearMonth) years.add(ym.split('/')[0])

      const yearNodes: FsNode[] = []
      for (const year of [...years].sort().reverse()) {
        yearNodes.push({ name: year, type: 'folder', path: `${sName}/${year}` })
      }
      tree.set(sName, yearNodes)

      for (const year of years) {
        const monthNodes: FsNode[] = []

        for (const [ym, ymShifts] of byYearMonth) {
          if (!ym.startsWith(year + '/')) continue
          const monthNum = Number(ym.split('/')[1])
          const monthName = MONTH_NAMES[monthNum] || ym

          const monthReceipts = (allReceipts ?? []).filter((r) => {
            if (!r.dt) return false
            const rd = new Date(r.dt)
            return rd.getFullYear() === Number(year) && (rd.getMonth() + 1) === monthNum
          })

          const totalItems = ymShifts.length + monthReceipts.length
          monthNodes.push({
            name: monthName, type: 'folder',
            path: `${sName}/${year}/${monthName}`,
            childCount: totalItems,
          })

          const monthContent: FsNode[] = []

          // Shifts subfolder
          if (filters.docType === 'all' || filters.docType === 'shifts') {
            monthContent.push({
              name: 'Смены', type: 'folder',
              path: `${sName}/${year}/${monthName}/Смены`,
              childCount: ymShifts.length,
            })
            const shiftFiles: FsNode[] = ymShifts.map((s) => ({
              name: `Смена №${s.shift}`,
              type: 'file' as const,
              path: `${sName}/${year}/${monthName}/Смены/Смена №${s.shift}`,
              shift: s,
              stationId: code,
              docType: 'shift' as const,
              date: s.dt_open ? format(new Date(s.dt_open), 'dd.MM.yyyy HH:mm') : '—',
              status: s.dt_close ? 'Закрыта' : 'Открыта',
              size: '—',
            }))
            tree.set(`${sName}/${year}/${monthName}/Смены`, shiftFiles)
          }

          // TTN subfolder
          if ((filters.docType === 'all' || filters.docType === 'receipts') && monthReceipts.length > 0) {
            monthContent.push({
              name: 'ТТН', type: 'folder',
              path: `${sName}/${year}/${monthName}/ТТН`,
              childCount: monthReceipts.length,
            })
            const receiptFiles: FsNode[] = monthReceipts.map((r, idx) => ({
              name: `ТТН ${r.ttn} — ${r.fuel}`,
              type: 'file' as const,
              path: `${sName}/${year}/${monthName}/ТТН/ТТН ${r.ttn}-${idx}`,
              docType: 'delivery' as const,
              date: r.dt ? format(new Date(r.dt), 'dd.MM.yyyy HH:mm') : '—',
              size: `${r.docVolume.toLocaleString('ru')} л`,
            }))
            tree.set(`${sName}/${year}/${monthName}/ТТН`, receiptFiles)
          }

          tree.set(`${sName}/${year}/${monthName}`, monthContent)
        }

        tree.set(`${sName}/${year}`, [...monthNodes])
      }

      // Update root childCount
      const rootIdx = rootNodes.findIndex((n) => n.name === sName)
      if (rootIdx >= 0) rootNodes[rootIdx].childCount = shifts.length
    }

    tree.set('', rootNodes)
    return tree
  }, [shifts, allReceipts, stId, settings.stations, filters])

  // Flatten tree into sorted file list (unified data source)
  const flatFiles = useMemo(() => {
    const files: FsNode[] = []
    for (const [, nodes] of fsTree) {
      for (const node of nodes) {
        if (node.type === 'file') files.push(node)
      }
    }

    // Sort
    files.sort((a, b) => {
      const dir = sortConfig.direction === 'asc' ? 1 : -1
      switch (sortConfig.column) {
        case 'name':
          return dir * a.name.localeCompare(b.name, 'ru')
        case 'date': {
          const da = a.shift?.dt_open || a.date || ''
          const db = b.shift?.dt_open || b.date || ''
          return dir * da.localeCompare(db)
        }
        case 'status': {
          const sa = a.status || ''
          const sb = b.status || ''
          return dir * sa.localeCompare(sb)
        }
        default:
          return 0
      }
    })

    return files
  }, [fsTree, sortConfig])

  // Count all leaf nodes
  const totalItemCount = useMemo(() => {
    let count = 0
    for (const [, nodes] of fsTree) {
      for (const node of nodes) {
        if (node.type === 'file') count++
      }
    }
    return count
  }, [fsTree])

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-all-receipts'] })
  }, [queryClient])

  return {
    fsTree,
    flatFiles,
    isLoading,
    isFetching,
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
