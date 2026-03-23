/**
 * Контекст рабочего стола — синхронизация между панелями.
 * Клик в RawPanel → selectedShift → CorePanel показывает детали.
 */

import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface ExportDocument {
  id: string
  type: 'receipt' | 'transfer' | 'assembly' | 'retail_sales'
  label: string
  sourceShift: number
  stationId: number
  status: 'draft' | 'confirmed' | 'exported'
  createdAt: string
}

interface WorkspaceContextType {
  /** Выбранная станция */
  selectedStationId: number | null
  /** Выбранная смена */
  selectedShiftNumber: number | null
  /** Активная вкладка (mobile) */
  activeTab: 'raw' | 'core' | 'export'

  /** Выбрать смену (из RawPanel) */
  selectShift: (stationId: number, shiftNumber: number) => void
  /** Сбросить выбор */
  clearSelection: () => void
  /** Переключить вкладку (mobile) */
  setActiveTab: (tab: 'raw' | 'core' | 'export') => void

  /** Документы для экспорта в 1С */
  exportDocs: ExportDocument[]
  /** Добавить документ в Export */
  addExportDoc: (doc: ExportDocument) => void
  /** Убрать документ из Export */
  removeExportDoc: (id: string) => void
  /** Пометить как выгруженный */
  markExported: (id: string) => void
}

const WorkspaceContext = createContext<WorkspaceContextType | null>(null)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [selectedStationId, setSelectedStationId] = useState<number | null>(null)
  const [selectedShiftNumber, setSelectedShiftNumber] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<'raw' | 'core' | 'export'>('raw')
  const [exportDocs, setExportDocs] = useState<ExportDocument[]>([])

  const selectShift = useCallback((stationId: number, shiftNumber: number) => {
    setSelectedStationId(stationId)
    setSelectedShiftNumber(shiftNumber)
    setActiveTab('core') // на мобильном автопереключение на Core
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedStationId(null)
    setSelectedShiftNumber(null)
  }, [])

  const addExportDoc = useCallback((doc: ExportDocument) => {
    setExportDocs((prev) => {
      if (prev.some((d) => d.id === doc.id)) return prev
      return [...prev, doc]
    })
  }, [])

  const removeExportDoc = useCallback((id: string) => {
    setExportDocs((prev) => prev.filter((d) => d.id !== id))
  }, [])

  const markExported = useCallback((id: string) => {
    setExportDocs((prev) =>
      prev.map((d) => (d.id === id ? { ...d, status: 'exported' as const } : d)),
    )
  }, [])

  return (
    <WorkspaceContext.Provider
      value={{
        selectedStationId,
        selectedShiftNumber,
        activeTab,
        selectShift,
        clearSelection,
        setActiveTab,
        exportDocs,
        addExportDoc,
        removeExportDoc,
        markExported,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider')
  return ctx
}
